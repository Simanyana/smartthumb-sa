#!/usr/bin/env bash
# SmartThumb SA - one-command deployment with the AWS CLI (v2).
#   ENABLE_REKOGNITION=false ./deploy/deploy.sh    # core thumbnail pipeline first (recommended)
#   ENABLE_REKOGNITION=true  ./deploy/deploy.sh    # re-run later to add AI labels
# Re-runnable: existing resources are updated, not duplicated.
set -euo pipefail
cd "$(dirname "$0")/.."

REGION="${REGION:-eu-west-1}"            # check Rekognition + pricing for your region
ENABLE_REK="${ENABLE_REKOGNITION:-false}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
SRC="smartthumb-sa-source-${ACCOUNT}"
DST="smartthumb-sa-thumbs-${ACCOUNT}"
FN="smartthumb-sa-processor"
ROLE="smartthumb-sa-lambda-role"
export AWS_DEFAULT_REGION="$REGION"

echo "== 1/6 Buckets (private, public access blocked, encrypted)"
for B in "$SRC" "$DST"; do
  if ! aws s3api head-bucket --bucket "$B" 2>/dev/null; then
    if [ "$REGION" = "us-east-1" ]; then
      aws s3api create-bucket --bucket "$B" >/dev/null
    else
      aws s3api create-bucket --bucket "$B" --create-bucket-configuration "LocationConstraint=$REGION" >/dev/null
    fi
  fi
  aws s3api put-public-access-block --bucket "$B" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
  aws s3api put-bucket-encryption --bucket "$B" --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
done

echo "== 2/6 IAM role (least privilege)"
if ! aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE" --assume-role-policy-document file://deploy/trust-policy.json >/dev/null
  NEW_ROLE=1
fi
POLICY_FILE="$(mktemp)"
sed -e "s/__SRC__/$SRC/g" -e "s/__DST__/$DST/g" -e "s/__REGION__/$REGION/g" \
    -e "s/__ACCOUNT__/$ACCOUNT/g" -e "s/__FN__/$FN/g" deploy/iam-policy-core.json > "$POLICY_FILE"
aws iam put-role-policy --role-name "$ROLE" --policy-name smartthumb-core --policy-document "file://$POLICY_FILE"
rm -f "$POLICY_FILE"
if [ "$ENABLE_REK" = "true" ]; then
  aws iam put-role-policy --role-name "$ROLE" --policy-name smartthumb-rekognition --policy-document file://deploy/iam-policy-rekognition.json
else
  aws iam delete-role-policy --role-name "$ROLE" --policy-name smartthumb-rekognition 2>/dev/null || true
fi
ROLE_ARN="$(aws iam get-role --role-name "$ROLE" --query Role.Arn --output text)"
[ "${NEW_ROLE:-0}" = "1" ] && { echo "   waiting for IAM propagation..."; sleep 12; }

echo "== 3/6 Package + log group (14-day retention keeps cost down)"
bash deploy/build.sh
aws logs create-log-group --log-group-name "/aws/lambda/$FN" 2>/dev/null || true
aws logs put-retention-policy --log-group-name "/aws/lambda/$FN" --retention-in-days 14

echo "== 4/6 Lambda function"
ENV="Variables={DEST_BUCKET=$DST,MAX_DIMENSION=300,ENABLE_REKOGNITION=$ENABLE_REK,LABEL_MIN_CONFIDENCE=70,MAX_LABELS=10}"
if aws lambda get-function --function-name "$FN" >/dev/null 2>&1; then
  aws lambda update-function-code --function-name "$FN" --zip-file fileb://build/smartthumb.zip >/dev/null
  aws lambda wait function-updated --function-name "$FN"
  aws lambda update-function-configuration --function-name "$FN" --environment "$ENV" --timeout 30 --memory-size 512 >/dev/null
else
  aws lambda create-function --function-name "$FN" --runtime python3.12 --architectures x86_64 \
    --handler lambda_function.lambda_handler --role "$ROLE_ARN" --timeout 30 --memory-size 512 \
    --environment "$ENV" --zip-file fileb://build/smartthumb.zip >/dev/null
fi
aws lambda wait function-active --function-name "$FN"
FN_ARN="$(aws lambda get-function --function-name "$FN" --query Configuration.FunctionArn --output text)"

echo "== 5/6 Allow ONLY the source bucket in this account to invoke the function"
aws lambda add-permission --function-name "$FN" --statement-id s3-invoke --action lambda:InvokeFunction \
  --principal s3.amazonaws.com --source-arn "arn:aws:s3:::$SRC" --source-account "$ACCOUNT" >/dev/null 2>&1 || true

echo "== 6/6 S3 ObjectCreated trigger (no suffix filter, so invalid files are tested and logged too)"
aws s3api put-bucket-notification-configuration --bucket "$SRC" --notification-configuration \
  "{\"LambdaFunctionConfigurations\":[{\"LambdaFunctionArn\":\"$FN_ARN\",\"Events\":[\"s3:ObjectCreated:*\"]}]}"

cat <<EOF

Deployed in $REGION (Rekognition labels: $ENABLE_REK)
  Source bucket : s3://$SRC
  Output bucket : s3://$DST   (thumbnails/ and labels/)
  Function      : $FN
Next: ./deploy/demo.sh      Cleanup: ./deploy/cleanup.sh
Remember to set an AWS Budget alert (Billing > Budgets).
EOF
