"""SmartThumb SA - S3-triggered product-image thumbnail generator.

Flow: S3 ObjectCreated (source bucket) -> validate -> Pillow thumbnail ->
put in DEST bucket -> (optional) Rekognition label suggestions -> CloudWatch logs.

Design rules (see README "Scenarios handled"):
  * Permanent problems (bad file, wrong type, too big) are REJECTED and logged,
    never raised, so Lambda does not retry pointlessly.
  * Transient problems (S3 throttling, network) are RAISED so Lambda's async
    retry runs. Output keys are deterministic, so retries/duplicate events
    simply overwrite the same thumbnail (idempotent).
  * Rekognition is an optional extra: if it fails, the thumbnail still succeeds.
  * Writes only go to DEST_BUCKET, never the trigger bucket (no recursion).
"""
import io
import json
import logging
import os
import time
import urllib.parse

from botocore.exceptions import ClientError
from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# ---- configuration (environment variables) ---------------------------------
DEST_BUCKET = os.environ.get("DEST_BUCKET", "")
MAX_DIM = int(os.environ.get("MAX_DIMENSION", "300"))
MAX_INPUT_BYTES = int(os.environ.get("MAX_INPUT_BYTES", str(15 * 1024 * 1024)))
MAX_PIXELS = int(os.environ.get("MAX_PIXELS", str(50_000_000)))
ENABLE_REKOGNITION = os.environ.get("ENABLE_REKOGNITION", "false").lower() == "true"
LABEL_MIN_CONFIDENCE = float(os.environ.get("LABEL_MIN_CONFIDENCE", "70"))
MAX_LABELS = int(os.environ.get("MAX_LABELS", "10"))
THUMB_PREFIX = os.environ.get("THUMB_PREFIX", "thumbnails/")
LABEL_PREFIX = os.environ.get("LABEL_PREFIX", "labels/")

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
ALLOWED_FORMATS = {"JPEG", "PNG"}
REKOGNITION_MAX_BYTES = 5 * 1024 * 1024  # inline-bytes limit for DetectLabels

Image.MAX_IMAGE_PIXELS = MAX_PIXELS * 2  # hard stop for decompression bombs

_s3 = None
_rek = None


def s3_client():
    global _s3
    if _s3 is None:
        import boto3
        _s3 = boto3.client("s3")
    return _s3


def rek_client():
    global _rek
    if _rek is None:
        import boto3
        _rek = boto3.client("rekognition")
    return _rek


def log(event, **fields):
    logger.info(json.dumps({"event": event, **fields}, default=str))


class InvalidImageError(Exception):
    """The file is not a usable JPG/PNG. Permanent: do not retry."""


# ---- pure image logic (unit-testable without AWS) --------------------------
def make_thumbnail(data, max_dim=MAX_DIM):
    """Return (thumb_bytes, fmt, original_size, thumb_size). Raises InvalidImageError."""
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = probe.format
            if fmt not in ALLOWED_FORMATS:
                raise InvalidImageError(f"unsupported_format:{fmt}")
            width, height = probe.size
            if width * height > MAX_PIXELS:
                raise InvalidImageError("too_many_pixels")
            probe.verify()  # detects many corrupt files without full decode

        with Image.open(io.BytesIO(data)) as img:
            img.load()  # forces full decode; catches truncated files
            img = ImageOps.exif_transpose(img)  # fix sideways phone photos
            original_size = img.size
            if img.mode in ("P", "LA", "PA"):
                img = img.convert("RGBA")
            elif img.mode == "CMYK" or (fmt == "JPEG" and img.mode not in ("RGB", "L")):
                img = img.convert("RGB")
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)  # keeps aspect ratio, never upscales
            out = io.BytesIO()
            if fmt == "PNG":
                img.save(out, "PNG", optimize=True)
            else:
                img.save(out, "JPEG", quality=85, optimize=True, progressive=True)
            return out.getvalue(), fmt, original_size, img.size
    except InvalidImageError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError) as exc:
        raise InvalidImageError(f"unreadable_image:{type(exc).__name__}") from exc


def thumbnail_key(src_key, fmt):
    base, ext = os.path.splitext(src_key)
    ext = ext.lower()
    if ext not in ALLOWED_EXTENSIONS or (fmt == "PNG") != (ext == ".png"):
        ext = ".png" if fmt == "PNG" else ".jpg"
    return f"{THUMB_PREFIX}{base}_thumb{ext}"


def labels_key(src_key):
    return f"{LABEL_PREFIX}{src_key}.json"


# ---- AWS-facing logic --------------------------------------------------------
def suggest_labels(original, size_hint):
    """Call Rekognition. Returns list of label dicts. Raises on AWS errors."""
    payload = original
    if len(original) > REKOGNITION_MAX_BYTES:
        payload, _, _, _ = make_thumbnail(original, 1280)
    resp = rek_client().detect_labels(
        Image={"Bytes": payload}, MaxLabels=MAX_LABELS, MinConfidence=LABEL_MIN_CONFIDENCE
    )
    return [
        {
            "name": lab["Name"],
            "confidence": round(lab["Confidence"], 1),
            "parents": [p["Name"] for p in lab.get("Parents", [])],
        }
        for lab in resp.get("Labels", [])
    ]


def process_record(rec):
    started = time.time()
    if rec.get("eventSource") != "aws:s3" or not str(rec.get("eventName", "")).startswith("ObjectCreated"):
        log("skipped", reason="not_object_created", name=rec.get("eventName"))
        return "skipped"

    bucket = rec["s3"]["bucket"]["name"]
    key = urllib.parse.unquote_plus(rec["s3"]["object"]["key"])  # keys arrive URL-encoded (spaces -> '+')

    if bucket == DEST_BUCKET:  # recursion guard
        log("skipped", reason="event_from_destination_bucket", bucket=bucket, key=key)
        return "skipped"
    if key.endswith("/"):
        log("skipped", reason="folder_placeholder", key=key)
        return "skipped"

    ext = os.path.splitext(key)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        log("rejected", reason="unsupported_extension", bucket=bucket, key=key, ext=ext)
        return "rejected"

    try:
        obj = s3_client().get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
            log("skipped", reason="object_deleted_before_processing", bucket=bucket, key=key)
            return "skipped"
        raise  # transient: let Lambda retry

    size = obj.get("ContentLength", 0)
    if size == 0:
        log("rejected", reason="empty_file", bucket=bucket, key=key)
        return "rejected"
    if size > MAX_INPUT_BYTES:
        log("rejected", reason="file_too_large", bucket=bucket, key=key, bytes=size, limit=MAX_INPUT_BYTES)
        return "rejected"

    data = obj["Body"].read()
    try:
        thumb, fmt, orig_dims, thumb_dims = make_thumbnail(data)
    except InvalidImageError as exc:
        log("rejected", reason=str(exc), bucket=bucket, key=key, bytes=size)
        return "rejected"

    out_key = thumbnail_key(key, fmt)
    s3_client().put_object(
        Bucket=DEST_BUCKET,
        Key=out_key,
        Body=thumb,
        ContentType="image/png" if fmt == "PNG" else "image/jpeg",
        Metadata={"source-bucket": bucket, "source-key": urllib.parse.quote(key)},
    )

    labels, labels_status = [], "disabled"
    if ENABLE_REKOGNITION:
        try:
            labels = suggest_labels(data, size)
            s3_client().put_object(
                Bucket=DEST_BUCKET,
                Key=labels_key(key),
                Body=json.dumps(
                    {
                        "source_key": key,
                        "thumbnail_key": out_key,
                        "labels": labels,
                        "review_status": "suggestion_pending_human_review",
                        "note": "AI suggestions only; may be broad or wrong. No brand/material/model claims.",
                    },
                    indent=2,
                ).encode(),
                ContentType="application/json",
            )
            labels_status = "ok"
        except Exception as exc:  # AI is optional: never fail the thumbnail
            labels_status = "failed"
            log("labels_failed", key=key, error=f"{type(exc).__name__}: {exc}")

    reduction = round((1 - len(thumb) / size) * 100, 1)
    log(
        "thumbnail_created",
        source_bucket=bucket,
        source_key=key,
        thumbnail_key=out_key,
        format=fmt,
        original_bytes=size,
        thumbnail_bytes=len(thumb),
        reduction_pct=reduction,
        original_dims=f"{orig_dims[0]}x{orig_dims[1]}",
        thumbnail_dims=f"{thumb_dims[0]}x{thumb_dims[1]}",
        labels_status=labels_status,
        labels=[l["name"] for l in labels],
        processing_ms=int((time.time() - started) * 1000),
    )
    return "processed"


def lambda_handler(event, context):
    if not DEST_BUCKET:
        raise RuntimeError("DEST_BUCKET environment variable is not set")
    records = event.get("Records") if isinstance(event, dict) else None
    if not records:  # e.g. s3:TestEvent sent when a notification is configured
        log("ignored_event", reason="no_records")
        return {"processed": 0, "rejected": 0, "skipped": 1, "errors": 0}

    counts = {"processed": 0, "rejected": 0, "skipped": 0, "errors": 0}
    first_error = None
    for rec in records:
        try:
            counts[process_record(rec)] += 1
        except Exception as exc:  # keep going so one bad record doesn't block others
            counts["errors"] += 1
            first_error = first_error or exc
            log("error", error=f"{type(exc).__name__}: {exc}")
    log("batch_summary", **counts)
    if first_error:
        raise first_error  # transient failure: trigger Lambda retry (idempotent)
    return counts
