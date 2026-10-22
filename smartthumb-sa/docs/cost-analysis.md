# Cost Analysis

The project is inexpensive at small scale but **not guaranteed to cost R0**. Do not quote prices from this file: look up current rates for your Region at https://aws.amazon.com/pricing/ and check Free Tier eligibility for your account.

## Cost drivers (per image)

| Service | Driver | What to record |
|---------|--------|----------------|
| S3 | Storage (original + thumbnail), PUT/GET requests | Average original and thumbnail size |
| Lambda | Requests + GB-seconds = (memory GB) × (duration s) | 512 MB; duration from CloudWatch `REPORT` lines |
| CloudWatch Logs | Ingestion + storage | ~1 JSON line per image + START/END/REPORT |
| Rekognition (optional) | Per image analysed | Number of DetectLabels calls |

## Estimate per 100 images (fill in with real numbers)

```
lambda_gb_seconds = 0.5 GB × avg_duration_s × 100
lambda_cost       = requests × price_per_request + lambda_gb_seconds × price_per_gb_second
s3_cost           = 100 × (PUT thumbnail price) + 100 × (GET original price) + storage GB-month × price
rekognition_cost  = 100 × price_per_image            (only if enabled)
logs_cost         = ingested_GB × price_per_GB
TOTAL             = sum above  (convert USD to ZAR at the day's rate)
```

| Input | Value from my tests |
|-------|--------------------|
| avg Lambda duration (ms) | |
| avg original size (KB) | |
| avg thumbnail size (KB) | |
| Rekognition calls | |
| Region used | |
| **Estimated cost per 100 images** | |

## Controls

Small batches (≈30 images), core pipeline first, Rekognition last, 14-day log retention, AWS Budget alert, delete everything with `deploy/cleanup.sh` after capturing screenshots.
