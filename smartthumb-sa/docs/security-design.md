# Security Design

| Control | Implementation |
|---------|----------------|
| Private storage | Both buckets: all four S3 Block Public Access settings on; no ACLs or public policies |
| Encryption at rest | SSE-S3 (AES-256) set explicitly on both buckets |
| Least-privilege IAM | Role allows only `s3:GetObject` on the source bucket, `s3:PutObject` on the output bucket, log-stream writes for this function's log group, and (only if enabled) `rekognition:DetectLabels` |
| No credentials in code | Lambda uses its execution role; nothing stored in the repo |
| Invocation restricted | Lambda resource policy lets only `s3.amazonaws.com` for the source bucket in this account invoke the function (`--source-arn` and `--source-account`) |
| No recursion | Separate buckets plus an in-code guard that ignores events from the output bucket |
| Hostile input | Content verified with Pillow (not just the extension), size cap, pixel cap (decompression-bomb defence), format allow-list (JPEG/PNG only) |
| Privacy | Use sample images or photos with the owner's permission; thumbnails drop EXIF/GPS metadata; labels are suggestions kept in the private output bucket |
| Auditability | Structured CloudWatch logs; 14-day retention |
| Cost safety | Budget alert (alerts are not hard limits), small test volumes, `cleanup.sh` |

## Residual risks

- Originals retain EXIF/GPS metadata in the source bucket.
- AI labels may be wrong; they are never presented as authoritative.
- Rekognition `DetectLabels` does not support resource-level restriction, so the policy uses `Resource: *` for that single action.
- Single account/region prototype: no cross-region failover or DLQ.
