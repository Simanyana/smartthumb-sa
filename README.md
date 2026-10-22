# SmartThumb SA

AI-assisted product-image processing for South African small businesses, built on AWS serverless (S3, Lambda, Rekognition, CloudWatch).

Upload a product photo to a private S3 bucket. Within seconds a 300 × 300 (max) thumbnail appears in a separate output bucket, and optionally AI-suggested catalogue labels. Every run is logged in CloudWatch.

> **Problem hypothesis (to validate):** small sellers who advertise via WhatsApp Business, social media and online catalogues spend time resizing and organising phone photos by hand. Interview 3-5 sellers (questions in `docs/problem-statement.md`) before calling this confirmed.

## Architecture

```
Seller/tester ──upload──▶ S3 source bucket (private)
                              │ ObjectCreated event
                              ▼
                     Lambda (Python 3.12 + Pillow)
                      validate → resize → write
                      │            │
        (optional)    ▼            ▼
              Rekognition     S3 output bucket (private)
              DetectLabels      thumbnails/…_thumb.jpg
                      │         labels/….json
                      ▼
                CloudWatch Logs (structured JSON, metrics source)
```

Diagram file: `architecture/architecture.svg`. Source and output are **separate buckets** so the function can never re-trigger itself.

## Requirements coverage

| ID | Requirement | How it is met | Evidence |
|----|-------------|---------------|----------|
| FR1 | Accept JPG/PNG uploads | Source bucket accepts any upload; code validates content, not just the extension | `tests/test_cases.md` TC01-TC10 |
| FR2 | Trigger automatically | S3 `ObjectCreated:*` notification → Lambda | `deploy/deploy.sh` step 6 |
| FR3 | Thumbnail ≤ 300 px, aspect ratio kept | `Image.thumbnail((300,300), LANCZOS)`, EXIF rotation fixed, never upscaled | `test_thumbnail_max_300_and_aspect_ratio` |
| FR4 | Store output separately | `put_object` only to `DEST_BUCKET` | `test_happy_path_writes_only_to_dest` |
| FR5 | AI labels (extension) | Rekognition `DetectLabels`, saved to `labels/*.json` as suggestions pending human review | `test_labels_written_when_enabled` |
| FR6 | Log execution | One structured JSON log line per outcome (`thumbnail_created`, `rejected`, `skipped`, `error`, `batch_summary`) | CloudWatch |
| FR7 | Handle invalid files | Rejected and logged, never an unhandled failure | `test_invalid_files_rejected_not_raised` |
| NFR | Security / least privilege | Public access blocked, SSE encryption, role limited to read-source, write-output, own logs, (optional) DetectLabels | `deploy/iam-policy-*.json`, `docs/security-design.md` |

## Scenarios handled (beyond the happy path)

| Scenario | Behaviour |
|----------|-----------|
| Wrong/missing extension, non-image bytes, empty file, truncated/corrupt JPG | Rejected + logged (`reason`), no retry storm |
| GIF, PDF, TXT | Rejected (unsupported extension/format) |
| PNG saved as `.jpg` | Accepted; real format detected from content |
| Uppercase `.JPG` (common from phones/cameras) | Handled |
| Sideways phone photos (EXIF orientation) | Auto-rotated before resizing |
| PNG with transparency, palette PNG, CMYK JPEG | Alpha preserved for PNG; converted safely |
| Already-small image (< 300 px) | Not upscaled; stored as-is size |
| Very wide / very tall images | Longest side capped at 300, ratio preserved |
| Huge file or pixel bomb | Rejected above `MAX_INPUT_BYTES` / `MAX_PIXELS` |
| Spaces/special characters in file names | S3 event key URL-decoded correctly |
| Folder placeholder objects, S3 test event, delete events | Ignored safely |
| Object deleted before processing | Logged and skipped |
| Duplicate/retried events | Deterministic output key → idempotent overwrite |
| Transient AWS errors (throttling) | Raised so Lambda's async retry runs |
| Rekognition down/not permitted/over 5 MB input | Thumbnail still succeeds; label failure logged; large inputs sent as 1280 px JPEG |
| Batch event with several records | Each handled independently |
| Output bucket event / recursion | Guard skips events from the output bucket |
| Cost runaway | Small test volumes, 14-day log retention, budget alert, `cleanup.sh` |

## Quick start

Prerequisites: Python 3.12+, AWS CLI v2 configured (`aws configure`), bash (Git Bash/WSL on Windows).

```bash
# 1. Generate the test dataset (valid + invalid files) and run unit tests
python tools/make_test_images.py
pip install -r requirements-dev.txt && pytest -q

# 2. Offline baseline (safety net for demos)
python tools/run_local.py

# 3. Deploy the core pipeline (thumbnails only)
ENABLE_REKOGNITION=false ./deploy/deploy.sh

# 4. Demo: upload one image, then all test images
./deploy/demo.sh tests/test_images/handbag_01.jpg
./deploy/demo.sh

# 5. Add the AI extension once the core works and cost is reviewed
ENABLE_REKOGNITION=true ./deploy/deploy.sh
./deploy/demo.sh path/to/your_real_product_photo.jpg   # then check labels/ in the output bucket

# 6. Collect real metrics from CloudWatch, then review labels
python tools/collect_metrics.py --region eu-west-1 --since-minutes 120
python tools/collect_metrics.py --review results/label_review.csv

# 7. Save screenshots, then remove everything
./deploy/cleanup.sh
```

Region: defaults to `eu-west-1`. Set `REGION=...` and confirm Rekognition availability and pricing for that region first.

## Configuration (Lambda environment variables)

| Variable | Default | Purpose |
|----------|---------|---------|
| `DEST_BUCKET` | required | Output bucket |
| `MAX_DIMENSION` | 300 | Thumbnail max width/height |
| `MAX_INPUT_BYTES` | 15 MB | Reject larger uploads |
| `MAX_PIXELS` | 50,000,000 | Reject decompression bombs |
| `ENABLE_REKOGNITION` | false | AI extension on/off |
| `LABEL_MIN_CONFIDENCE` / `MAX_LABELS` | 70 / 10 | Label filtering |

## Results

Measured on 22 October 2026 in AWS eu-west-1 (Ireland) using CloudWatch logs (`tools/collect_metrics.py`, `results/processing_metrics.csv`). Targets are provisional.

**Test set:** 26 valid synthetic test images plus 1 real product photo (28 successful runs, because `handbag_01.jpg` was uploaded twice), and 6 invalid files (34 Lambda invocations in total).

| Metric | Target | Actual |
|--------|--------|--------|
| Average size reduction | ≥ 50% | **80.3%** across 28 runs. Most inputs were large synthetic images, so a real-world figure for small or already-compressed phone photos will be lower. |
| Valid-image success rate | ≥ 95% | **100%** (28/28 valid runs, 0 errors) |
| Invalid-file handling | no unhandled failures | **6/6** invalid files rejected and logged with a reason, with no errors |
| Automatic triggering | 100% | **100%**: every upload invoked Lambda with no manual run |
| Lambda duration | baseline | **Average 399 ms, maximum 2,690 ms** (34 invocations, from CloudWatch REPORT lines) |
| Useful AI labels | ≥ 80% | **TO FILL**: 6 labels returned for one real photo (Accessories, Bag, Handbag, Purse, Jewelry, Necklace); reviewer verdict pending. One photo is too small a sample to generalise. |
| Manual time saved | measure | **TO FILL**: time 5 manual resizes and compare |
| Est. cost / 100 images | calculate | **TO FILL** from Billing (Cost Explorer can lag up to a day); method in `docs/cost-analysis.md` |

## Limitations

- Prototype, not production: no UI, accounts, database or catalogue.
- Rekognition labels are broad suggestions, can be wrong, and never identify brand, material or model.
- Already-compressed small images may shrink by far less than 50%, or even grow slightly after re-encoding.
- Metadata (EXIF/GPS) is dropped from thumbnails, which is good for privacy, but the originals still contain it.
- Test images are synthetic; label usefulness must be judged on real, permission-cleared product photos.

## Next steps

Seller interviews, a simple upload page with presigned URLs, WhatsApp-friendly size presets, a DynamoDB catalogue, SNS/DLQ alerts on failures.

## Repository layout

```
src/lambda_function.py   deploy/ (build, deploy, demo, cleanup, IAM)   tools/ (images, local run, metrics)
tests/                   results/                                       docs/    architecture/
```
