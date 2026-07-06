#!/bin/bash
# Deploy the fall go-live checklist: DynamoDB table + Lambda (Function URL) +
# S3 static site. Idempotent — safe to re-run any time index.html or
# lambda_function.py change.
set -e

BUCKET="attenddance-checklist"
REGION="us-east-1"
TABLE="attenddance-checklist"
FUNCTION_NAME="attenddance-checklist"
ROLE_NAME="attenddance-checklist-lambda-role"
ACCOUNT_ID="360176309871"
PROFILE="attenddance-checklist-deploy"

cd "$(dirname "$0")"

# aws lambda wait function-active/function-updated poll via GetFunctionConfiguration,
# which this deploy identity is deliberately NOT granted (least privilege — it only
# has GetFunction). Poll with GetFunction instead, which exposes the same State /
# LastUpdateStatus fields.
wait_for_lambda_ready() {
  for _ in $(seq 1 30); do
    read -r STATE UPDATE_STATUS <<< "$(aws lambda get-function --function-name "$FUNCTION_NAME" \
      --profile "$PROFILE" --region "$REGION" \
      --query 'Configuration.[State,LastUpdateStatus]' --output text 2>/dev/null)"
    if [ "$STATE" = "Active" ] && [ "$UPDATE_STATUS" = "Successful" ]; then
      return 0
    fi
    sleep 2
  done
  echo "  WARNING: function did not reach Active/Successful within 60s" >&2
}

echo "== 1/7 DynamoDB table =="
if ! aws dynamodb describe-table --table-name "$TABLE" --profile "$PROFILE" --region "$REGION" >/dev/null 2>&1; then
  aws dynamodb create-table \
    --table-name "$TABLE" \
    --attribute-definitions AttributeName=list_id,AttributeType=S AttributeName=item_id,AttributeType=S \
    --key-schema AttributeName=list_id,KeyType=HASH AttributeName=item_id,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST \
    --profile "$PROFILE" --region "$REGION" >/dev/null
  aws dynamodb wait table-exists --table-name "$TABLE" --profile "$PROFILE" --region "$REGION"
  echo "  created + active"
else
  echo "  already exists"
fi

echo "== 2/7 S3 bucket + static website hosting =="
aws s3 mb "s3://$BUCKET" --region "$REGION" --profile "$PROFILE" 2>/dev/null || echo "  bucket already exists"
aws s3 website "s3://$BUCKET" --index-document index.html --profile "$PROFILE"
aws s3api put-public-access-block --bucket "$BUCKET" --profile "$PROFILE" \
  --public-access-block-configuration "BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false"
aws s3api put-bucket-policy --bucket "$BUCKET" --profile "$PROFILE" --policy '{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "PublicReadGetObject",
    "Effect": "Allow",
    "Principal": "*",
    "Action": "s3:GetObject",
    "Resource": "arn:aws:s3:::'"$BUCKET"'/*"
  }]
}'
echo "  configured"

echo "== 3/7 IAM role for Lambda =="
if ! aws iam get-role --role-name "$ROLE_NAME" --profile "$PROFILE" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE_NAME" --profile "$PROFILE" \
    --assume-role-policy-document '{
      "Version":"2012-10-17",
      "Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]
    }' >/dev/null
  echo "  created role, waiting for IAM propagation..."
  ROLE_JUST_CREATED=1
else
  echo "  already exists"
  ROLE_JUST_CREATED=0
fi

aws iam attach-role-policy --role-name "$ROLE_NAME" --profile "$PROFILE" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

aws iam put-role-policy --role-name "$ROLE_NAME" --profile "$PROFILE" \
  --policy-name attenddance-checklist-ddb-access \
  --policy-document file://ddb-policy.json

if [ "$ROLE_JUST_CREATED" = "1" ]; then
  sleep 10
fi

echo "== 4/7 Lambda function =="
zip -q -j function.zip lambda_function.py
if aws lambda get-function --function-name "$FUNCTION_NAME" --profile "$PROFILE" --region "$REGION" >/dev/null 2>&1; then
  aws lambda update-function-code --function-name "$FUNCTION_NAME" --zip-file fileb://function.zip \
    --profile "$PROFILE" --region "$REGION" >/dev/null
  wait_for_lambda_ready
  echo "  code updated"
else
  aws lambda create-function --function-name "$FUNCTION_NAME" \
    --runtime python3.12 --handler lambda_function.handler \
    --role "arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}" \
    --zip-file fileb://function.zip \
    --timeout 10 --memory-size 128 \
    --profile "$PROFILE" --region "$REGION" >/dev/null
  wait_for_lambda_ready
  echo "  created"
fi

ORIGIN="http://$BUCKET.s3-website-$REGION.amazonaws.com"
aws lambda update-function-configuration --function-name "$FUNCTION_NAME" \
  --environment "Variables={TABLE_NAME=$TABLE,ALLOWED_ORIGIN=$ORIGIN}" \
  --profile "$PROFILE" --region "$REGION" >/dev/null
wait_for_lambda_ready
rm -f function.zip

echo "== 5/7 Function URL + CORS =="
if aws lambda get-function-url-config --function-name "$FUNCTION_NAME" --profile "$PROFILE" --region "$REGION" >/dev/null 2>&1; then
  aws lambda update-function-url-config --function-name "$FUNCTION_NAME" \
    --auth-type NONE \
    --cors "AllowOrigins=$ORIGIN,AllowMethods=GET,POST,AllowHeaders=content-type,MaxAge=300" \
    --profile "$PROFILE" --region "$REGION" >/dev/null
else
  aws lambda create-function-url-config --function-name "$FUNCTION_NAME" \
    --auth-type NONE \
    --cors "AllowOrigins=$ORIGIN,AllowMethods=GET,POST,AllowHeaders=content-type,MaxAge=300" \
    --profile "$PROFILE" --region "$REGION" >/dev/null
fi
# A Function URL with AuthType=NONE needs BOTH of these resource-policy grants
# to actually allow anonymous invocation — the AWS console's own "missing
# permissions" banner is what surfaces this; it's not obvious from the CLI docs.
aws lambda add-permission --function-name "$FUNCTION_NAME" \
  --action lambda:InvokeFunctionUrl --principal "*" \
  --function-url-auth-type NONE --statement-id FunctionURLAllowPublicAccess \
  --profile "$PROFILE" --region "$REGION" >/dev/null 2>&1 || true
aws lambda add-permission --function-name "$FUNCTION_NAME" \
  --action lambda:InvokeFunction --principal "*" \
  --statement-id FunctionURLAllowPublicInvoke \
  --profile "$PROFILE" --region "$REGION" >/dev/null 2>&1 || true

API_URL=$(aws lambda get-function-url-config --function-name "$FUNCTION_NAME" \
  --profile "$PROFILE" --region "$REGION" --query FunctionUrl --output text)
API_URL="${API_URL%/}"
echo "  Function URL: $API_URL"

echo "== 6/7 Render + upload frontend =="
sed "s|__API_BASE__|${API_URL}|g" index.html > /tmp/attenddance-checklist-index.html
aws s3 cp /tmp/attenddance-checklist-index.html "s3://$BUCKET/index.html" --profile "$PROFILE" \
  --content-type "text/html" >/dev/null
aws s3 sync assets/ "s3://$BUCKET/assets/" --profile "$PROFILE" --delete >/dev/null
rm -f /tmp/attenddance-checklist-index.html
echo "  uploaded"

echo "== 7/7 Seed checklist items =="
python3 seed.py

echo ""
echo "Done."
echo "  Site:   $ORIGIN"
echo "  API:    $API_URL"
