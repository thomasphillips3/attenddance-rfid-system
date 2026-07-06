#!/bin/bash
# Deploy the fall go-live checklist as a plain static S3 site. The shared/live
# backend is a Google Sheet + Apps Script (see Code.gs + README.md) — no AWS
# Lambda, DynamoDB, or IAM involved at all.
set -e

BUCKET="attenddance-checklist"
REGION="us-east-1"
PROFILE="attenddance-checklist-deploy"

# Set once, after deploying the Apps Script Web App (see README.md) — the
# URL ending in /exec. Left as a placeholder so this script fails loudly
# instead of shipping a broken page if you forget to set it.
APPS_SCRIPT_URL="https://script.google.com/macros/s/AKfycbzLEIPL6hnEkghLoCvY-3S5kRJOZqW6KTesvlBLs0ZWmhDhkWYnJYvF8WUkgXwf3L4VRA/exec"

cd "$(dirname "$0")"

if [ "$APPS_SCRIPT_URL" = "__SET_ME__" ]; then
  echo "Set APPS_SCRIPT_URL at the top of deploy.sh to your Apps Script /exec URL first." >&2
  exit 1
fi

echo "== 1/2 S3 bucket + static website hosting =="
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

echo "== 2/2 Render + upload frontend =="
sed "s|__API_BASE__|${APPS_SCRIPT_URL}|g" index.html > /tmp/attenddance-checklist-index.html
aws s3 cp /tmp/attenddance-checklist-index.html "s3://$BUCKET/index.html" --profile "$PROFILE" \
  --content-type "text/html" >/dev/null
aws s3 sync assets/ "s3://$BUCKET/assets/" --profile "$PROFILE" --delete >/dev/null
rm -f /tmp/attenddance-checklist-index.html
echo "  uploaded"

echo ""
echo "Done."
echo "  Site: http://$BUCKET.s3-website-$REGION.amazonaws.com"
