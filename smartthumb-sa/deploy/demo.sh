#!/usr/bin/env bash
# Upload every file in tests/test_images/ and show what appears in the output bucket.
#   ./deploy/demo.sh            # all test images (valid + invalid)
#   ./deploy/demo.sh path.jpg   # a single file (best for the live demo)
set -euo pipefail
cd "$(dirname "$0")/.."
REGION="${REGION:-eu-west-1}"; export AWS_DEFAULT_REGION="$REGION"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
SRC="smartthumb-sa-source-${ACCOUNT}"; DST="smartthumb-sa-thumbs-${ACCOUNT}"; FN="smartthumb-sa-processor"

if [ $# -ge 1 ]; then FILES=("$@"); else FILES=(tests/test_images/*); fi
for f in "${FILES[@]}"; do
  echo "upload -> $(basename "$f")"; aws s3 cp "$f" "s3://$SRC/$(basename "$f")" --only-show-errors
done
echo "waiting 15s for Lambda..."; sleep 15
echo; echo "== Output bucket"; aws s3 ls "s3://$DST/" --recursive --human-readable
echo; echo "== Latest CloudWatch events (processed / rejected)"
aws logs tail "/aws/lambda/$FN" --since 5m --format short | grep -E '"event"' | head -40 || true
mkdir -p results/downloaded && aws s3 sync "s3://$DST/thumbnails/" results/downloaded/ --only-show-errors
echo "Thumbnails downloaded to results/downloaded/"
