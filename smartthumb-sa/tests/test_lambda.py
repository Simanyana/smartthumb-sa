"""Local tests (no AWS needed):  pip install -r requirements-dev.txt && pytest -q"""
import io
import json
import os
import sys

os.environ["DEST_BUCKET"] = "dest-bucket"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from botocore.exceptions import ClientError
from PIL import Image

import lambda_function as lf


def img_bytes(w, h, fmt="JPEG", mode="RGB", exif=None):
    buf = io.BytesIO()
    kw = {"exif": exif} if exif else {}
    Image.effect_noise((w, h), 80).convert(mode).save(buf, fmt, **kw)
    return buf.getvalue()


class FakeS3:
    def __init__(self, objects):
        self.objects = dict(objects)
        self.puts = []
        self.fail_get = None

    def get_object(self, Bucket, Key):
        if self.fail_get:
            raise ClientError({"Error": {"Code": self.fail_get, "Message": "x"}}, "GetObject")
        if (Bucket, Key) not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "x"}}, "GetObject")
        data = self.objects[(Bucket, Key)]
        return {"Body": io.BytesIO(data), "ContentLength": len(data)}

    def put_object(self, **kw):
        self.objects[(kw["Bucket"], kw["Key"])] = kw["Body"]
        self.puts.append(kw)


class FakeRek:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    def detect_labels(self, **kw):
        self.calls += 1
        if self.fail:
            raise RuntimeError("rekognition down")
        return {"Labels": [{"Name": "Handbag", "Confidence": 98.2, "Parents": [{"Name": "Bag"}]}]}


def event(key, bucket="src-bucket", name="ObjectCreated:Put"):
    return {"Records": [{"eventSource": "aws:s3", "eventName": name, "s3": {"bucket": {"name": bucket}, "object": {"key": key}}}]}


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    monkeypatch.setattr(lf, "ENABLE_REKOGNITION", False)
    monkeypatch.setattr(lf, "_rek", None)


def run(key, data, monkeypatch, **kw):
    fake = FakeS3({("src-bucket", key): data})
    monkeypatch.setattr(lf, "_s3", fake)
    return fake, lf.lambda_handler(event(key), None)


# ---- FR3: sizing -------------------------------------------------------------
@pytest.mark.parametrize("w,h", [(4000, 3000), (3000, 4000), (6000, 1200), (1000, 5000), (800, 800)])
def test_thumbnail_max_300_and_aspect_ratio(w, h):
    out, fmt, orig, size = lf.make_thumbnail(img_bytes(w, h))
    assert max(size) == 300
    assert abs(size[0] / size[1] - w / h) < 0.02
    assert Image.open(io.BytesIO(out)).size == size


def test_small_image_not_upscaled():
    _, _, _, size = lf.make_thumbnail(img_bytes(200, 150))
    assert size == (200, 150)


def test_png_alpha_preserved():
    data = img_bytes(800, 600, "PNG", "RGBA")
    out, fmt, _, _ = lf.make_thumbnail(data)
    assert fmt == "PNG" and Image.open(io.BytesIO(out)).mode == "RGBA"


def test_exif_rotation_applied():
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate: landscape file displays as portrait
    out, _, orig, size = lf.make_thumbnail(img_bytes(1600, 1000, exif=exif))
    assert orig == (1000, 1600) and size[1] == 300 and size[0] < size[1]


def test_png_with_jpg_extension_uses_content_format():
    assert lf.thumbnail_key("a.jpg", "PNG").endswith("a_thumb.png")


# ---- FR7: invalid files ------------------------------------------------------
@pytest.mark.parametrize(
    "key,data",
    [
        ("fake.jpg", b"plain text"),
        ("empty.png", b""),
        ("trunc.jpg", img_bytes(2000, 1500)[:5000]),
        ("anim.gif", img_bytes(100, 100, "GIF", "P")),
        ("notes.txt", b"hello"),
        ("doc.pdf", b"%PDF-1.4"),
    ],
)
def test_invalid_files_rejected_not_raised(key, data, monkeypatch):
    fake, res = run(key, data, monkeypatch)
    assert res["rejected"] == 1 and res["errors"] == 0 and fake.puts == []


def test_oversize_rejected(monkeypatch):
    monkeypatch.setattr(lf, "MAX_INPUT_BYTES", 1000)
    fake, res = run("big.jpg", img_bytes(1000, 1000), monkeypatch)
    assert res["rejected"] == 1 and fake.puts == []


def test_pixel_bomb_rejected(monkeypatch):
    monkeypatch.setattr(lf, "MAX_PIXELS", 1000)
    fake, res = run("bomb.jpg", img_bytes(100, 100), monkeypatch)
    assert res["rejected"] == 1


# ---- FR2/FR4: happy path, keys, events -------------------------------------
def test_happy_path_writes_only_to_dest(monkeypatch):
    fake, res = run("shoes/red_shoe.JPG", img_bytes(2000, 1500), monkeypatch)
    assert res["processed"] == 1  # uppercase extension handled
    assert fake.puts and all(p["Bucket"] == "dest-bucket" for p in fake.puts)
    assert fake.puts[0]["Key"] == "thumbnails/shoes/red_shoe_thumb.jpg"


def test_url_encoded_key_decoded(monkeypatch):
    fake = FakeS3({("src-bucket", "my shoes/red bag.jpg"): img_bytes(1200, 900)})
    monkeypatch.setattr(lf, "_s3", fake)
    res = lf.lambda_handler(event("my+shoes/red+bag.jpg"), None)
    assert res["processed"] == 1
    assert fake.puts[0]["Key"] == "thumbnails/my shoes/red bag_thumb.jpg"


def test_recursion_guard(monkeypatch):
    fake = FakeS3({})
    monkeypatch.setattr(lf, "_s3", fake)
    res = lf.lambda_handler(event("thumbnails/a_thumb.jpg", bucket="dest-bucket"), None)
    assert res["skipped"] == 1 and fake.puts == []


def test_s3_test_event_and_non_create_events_ignored(monkeypatch):
    monkeypatch.setattr(lf, "_s3", FakeS3({}))
    assert lf.lambda_handler({"Event": "s3:TestEvent"}, None)["skipped"] == 1
    assert lf.lambda_handler(event("a.jpg", name="ObjectRemoved:Delete"), None)["skipped"] == 1


def test_folder_placeholder_skipped(monkeypatch):
    monkeypatch.setattr(lf, "_s3", FakeS3({}))
    assert lf.lambda_handler(event("folder/"), None)["skipped"] == 1


def test_object_deleted_before_processing(monkeypatch):
    monkeypatch.setattr(lf, "_s3", FakeS3({}))
    assert lf.lambda_handler(event("gone.jpg"), None)["skipped"] == 1


def test_transient_s3_error_raises_for_retry(monkeypatch):
    fake = FakeS3({("src-bucket", "a.jpg"): img_bytes(500, 500)})
    fake.fail_get = "SlowDown"
    monkeypatch.setattr(lf, "_s3", fake)
    with pytest.raises(ClientError):
        lf.lambda_handler(event("a.jpg"), None)


def test_duplicate_events_idempotent(monkeypatch):
    fake = FakeS3({("src-bucket", "a.jpg"): img_bytes(1500, 1000)})
    monkeypatch.setattr(lf, "_s3", fake)
    lf.lambda_handler(event("a.jpg"), None)
    lf.lambda_handler(event("a.jpg"), None)
    assert len([k for k in fake.objects if k[0] == "dest-bucket"]) == 1


def test_multi_record_batch_one_bad(monkeypatch):
    fake = FakeS3({("src-bucket", "ok.jpg"): img_bytes(900, 600), ("src-bucket", "bad.jpg"): b"junk"})
    monkeypatch.setattr(lf, "_s3", fake)
    ev = {"Records": event("ok.jpg")["Records"] + event("bad.jpg")["Records"]}
    res = lf.lambda_handler(ev, None)
    assert res["processed"] == 1 and res["rejected"] == 1


# ---- FR5: AI extension -------------------------------------------------------
def test_labels_written_when_enabled(monkeypatch):
    monkeypatch.setattr(lf, "ENABLE_REKOGNITION", True)
    monkeypatch.setattr(lf, "_rek", FakeRek())
    fake, res = run("bag.jpg", img_bytes(1200, 900), monkeypatch)
    label_put = [p for p in fake.puts if p["Key"].startswith("labels/")][0]
    body = json.loads(label_put["Body"])
    assert body["labels"][0]["name"] == "Handbag" and body["review_status"].endswith("human_review")


def test_rekognition_failure_does_not_fail_thumbnail(monkeypatch):
    monkeypatch.setattr(lf, "ENABLE_REKOGNITION", True)
    monkeypatch.setattr(lf, "_rek", FakeRek(fail=True))
    fake, res = run("bag.jpg", img_bytes(1200, 900), monkeypatch)
    assert res["processed"] == 1 and any(p["Key"].startswith("thumbnails/") for p in fake.puts)


def test_rekognition_not_called_when_disabled(monkeypatch):
    rek = FakeRek()
    monkeypatch.setattr(lf, "_rek", rek)
    run("bag.jpg", img_bytes(1200, 900), monkeypatch)
    assert rek.calls == 0
