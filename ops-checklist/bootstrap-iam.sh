#!/bin/bash
# One-time setup: creates a dedicated IAM user scoped ONLY to this project's
# three resources (the attenddance-checklist DynamoDB table, Lambda function,
# and its execution role). Run this once, yourself, from a session/profile
# that has IAM admin rights — NOT from splitz-deployment or any other
# project's deploy identity.
#
# Usage: ./bootstrap-iam.sh [--profile your-admin-profile]
set -e

USER_NAME="attenddance-checklist-deploy"
POLICY_NAME="attenddance-checklist-deploy-policy"

PROFILE_ARGS=()
if [ "$1" = "--profile" ] && [ -n "$2" ]; then
  PROFILE_ARGS=(--profile "$2")
fi

cd "$(dirname "$0")"

echo "== Creating dedicated IAM user: $USER_NAME =="
if aws iam get-user --user-name "$USER_NAME" "${PROFILE_ARGS[@]}" >/dev/null 2>&1; then
  echo "  already exists"
else
  aws iam create-user --user-name "$USER_NAME" "${PROFILE_ARGS[@]}" >/dev/null
  echo "  created"
fi

echo "== Attaching least-privilege inline policy (scoped to this project's 3 resources only) =="
aws iam put-user-policy --user-name "$USER_NAME" \
  --policy-name "$POLICY_NAME" \
  --policy-document file://deploy-iam-policy.json \
  "${PROFILE_ARGS[@]}"
echo "  attached"

echo "== Access key =="
EXISTING_KEYS=$(aws iam list-access-keys --user-name "$USER_NAME" "${PROFILE_ARGS[@]}" --query 'AccessKeyMetadata | length(@)' --output text)
if [ "$EXISTING_KEYS" -gt 0 ]; then
  echo "  $USER_NAME already has $EXISTING_KEYS active access key(s) — not creating another."
  echo "  If you need a fresh one, delete the old one first: aws iam list-access-keys --user-name $USER_NAME"
else
  echo "  Creating a new access key (shown once — copy it now):"
  echo ""
  aws iam create-access-key --user-name "$USER_NAME" "${PROFILE_ARGS[@]}"
  echo ""
fi

echo "Next: run 'aws configure --profile attenddance-checklist-deploy' with the"
echo "key above (region: us-east-1), then tell Claude the profile is ready."
