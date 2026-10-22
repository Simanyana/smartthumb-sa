#!/usr/bin/env bash
# Removes everything the project created (stop charges). Save screenshots/metrics FIRST.
set -uo pipefail
REGION="${REGION:-eu-west-1}"; export AWS_DEFAULT_REGION="$REGION"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
SRC="smartthumb-sa-source-${ACCOUNT}"; DST="smartthumb-sa-thumbs-${ACCOUNT}"
FN="smartthumb-sa-processor"; ROLE="smartthumb-sa-lambda-role"
read -r -p "Delete ALL SmartThumb SA resources in $REGION (account $ACCOUNT)? type yes: " ans
[ "$ans" = "yes" ] || { echo "aborted"; exit 1; }
aws s3api put-bucket-notification-configuration --bucket "$SRC" --notification-configuration '{}' 2>/dev/null
aws lambda delete-function --function-name "$FN" 2>/dev/null
aws logs delete-log-group --log-group-name "/aws/lambda/$FN" 2>/dev/null
for P in smartthumb-core smartthumb-rekognition; do aws iam delete-role-policy --role-name "$ROLE" --policy-name "$P" 2>/dev/null; done
aws iam delete-role --role-name "$ROLE" 2>/dev/null
for B in "$SRC" "$DST"; do aws s3 rm "s3://$B" --recursive 2>/dev/null; aws s3api delete-bucket --bucket "$B" 2>/dev/null; done
echo "Cleanup done. Verify in the console: S3, Lambda, IAM, CloudWatch Logs."
