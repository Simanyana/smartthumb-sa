# Friday 09:00 Presentation Script (10 minutes)

Structure follows the organisers' guidelines exactly. Total: 1 + 1 + 1 + 3 + 1 + 1 + 2 = 10 min.

## Before 09:00 checklist

- [ ] `./deploy/deploy.sh` already run; test one upload the night before
- [ ] Terminal 1 ready: `./deploy/demo.sh tests/test_images/handbag_01.jpg`
- [ ] AWS Console tabs open: S3 source bucket, S3 output bucket, CloudWatch log group
- [ ] One real, permission-cleared product photo ready for the AI demo (Rekognition on)
- [ ] Offline fallback ready: `python tools/run_local.py` and `results/local_thumbnails/`
- [ ] Screenshots saved (S3 input/output, Lambda config, CloudWatch logs, IAM policy)
- [ ] Phone hotspot as network backup

## 1. Introduction (1 min)
"I'm Botlhale Mathiba, and this is **SmartThumb SA**: an event-driven AWS pipeline that automatically turns phone photos of products into small, consistent thumbnails and suggests catalogue labels."

## 2. Problem (1 min)
Small South African sellers promote products on WhatsApp Business and social media using phone photos. Resizing and organising those photos by hand is repetitive, and inconsistent sizes make catalogues messy. This is my problem hypothesis. I have prepared interview questions to validate it with real sellers, and I won't claim every seller has this problem.

## 3. Solution (1 min)
Upload to a private S3 bucket → Lambda validates and resizes automatically → thumbnail saved to a separate bucket → optional Amazon Rekognition suggests labels for the owner to review. It's serverless, so there are no servers to manage and you pay only for use. Key features: automatic, private, safe with bad files, and AI used only as a human-reviewed suggestion.

## 4. Live demo (3 min)
1. (30 s) Show the architecture diagram, then the two empty/private buckets.
2. (60 s) Upload `handbag_01.jpg` (4000×3000, several MB). Show the thumbnail appear in the output bucket (≤300 px, much smaller). Compare sizes.
3. (45 s) Upload a bad file (`INVALID_not_an_image.jpg` and `INVALID_notes.txt`): show no thumbnail and the CloudWatch line `rejected` with its reason.
4. (45 s) Upload your real product photo with Rekognition on: open `labels/….json` and show the suggested labels. Say: "These are suggestions, and a person reviews them."
If the network fails: run `python tools/run_local.py`, show `results/local_baseline_metrics.csv`, and state clearly that it is the local run of the same code.

## 5. Technologies and implementation (1 min)
Python 3.12, Pillow, Amazon S3 event notification, AWS Lambda, IAM least privilege, CloudWatch, Rekognition, AWS CLI deployment scripts. Behind the scenes: the S3 event carries the key (URL-encoded, so I decode it); the function checks content with Pillow, fixes phone-photo rotation, resizes, and writes to the output bucket; each outcome is one structured JSON log line. Hardest part: packaging Pillow for the Lambda Linux runtime and handling the many edge cases (corrupt files, retries, recursion).

## 6. Challenges and lessons (1 min)
- Recursive trigger risk → separate buckets plus an in-code guard.
- Pillow packaging → build the Linux wheel for the Lambda runtime.
- Bad inputs → reject permanently-bad files (no retries), retry only transient errors, idempotent output keys.
- Optional AI must never break the core → thumbnails succeed even if Rekognition fails.
With more time: seller interviews, an upload web page with presigned URLs, DLQ/alerts, a catalogue database.

## 7. Conclusion and questions (2 min)
Value: saves manual effort, standardises catalogue images at very low cost, built securely and measured honestly. Be ready to state actual numbers from your run: success rate, average size reduction, duration, estimated cost. Say what is not yet proven: label usefulness on real products, and real-seller validation.
Next: validate with 3-5 sellers, measure manual time saved, add a simple upload page.

## Likely questions and answers

| Question | Answer |
|----------|--------|
| Why separate buckets? | Writing back into the trigger bucket would re-invoke Lambda in a loop; plus a code guard as defence in depth |
| Why not rely on file extensions? | They can be wrong or hostile; Pillow verifies the real content |
| What if Lambda fails? | Bad files: rejected and logged. Transient errors: raised so Lambda retries, and keys are deterministic so retries are safe |
| Is the AI accurate? | Not guaranteed; treated as suggestions, with human review and a measured usefulness target (≥ 80%, provisional) |
| How is it secured? | Private encrypted buckets, least-privilege role, Lambda invocable only by the source bucket |
| Cost? | Present your calculated figure from `docs/cost-analysis.md`; "not guaranteed R0" |
| Scale? | Lambda scales per upload; limits: 15 MB / 50 MP caps, account concurrency |
| What's your own contribution? | Everything in the repo: design, code, IAM, scripts, tests, docs. Be ready to explain any file |
