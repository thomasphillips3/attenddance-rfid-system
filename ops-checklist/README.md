# Fall Go-Live Checklist

A tiny shared checklist for Wilkanda and Carollette to track AttenDANCE's fall
stand-up together, live, from their phones. Not part of the AttenDANCE app —
lives in this folder for convenience, deploys to its own S3 site + Lambda.

## Live URLs

Printed at the end of `./deploy.sh`. Re-run the script any time to get them
again:
```
aws lambda get-function-url-config --function-name attenddance-checklist \
  --profile attenddance-checklist-deploy --region us-east-1 --query FunctionUrl --output text
```
Site: `http://attenddance-checklist.s3-website-us-east-1.amazonaws.com`

## How it works

- One shared checklist (DynamoDB table `attenddance-checklist`), no login.
- A **Simple / Detailed** toggle switches the whole page between short titles
  only and full instructions — same list, same data, just how much shows.
- Checking something off asks "who's checking in?" once per device (so
  completed items show who did them), then remembers it via localStorage.
- Updates every ~15s and instantly on refocus, so both of them see each
  other's check-offs without doing anything.

## Adding a new item

Edit the `ITEMS` list in `seed.py`, then run:
```
python3 seed.py
```
It's idempotent — only inserts items that don't already exist (matched by
`item_id`), never touches an item that's already been checked off. No
frontend changes needed.

## Redeploying after an edit

```
./deploy.sh
```
Safe to re-run any time — it's idempotent end to end (table, bucket, IAM role,
Lambda, Function URL, and the seed step at the very end).

## First-time setup: dedicated AWS identity

This project deploys under its own IAM user — **not** any other project's
deploy identity — scoped to only the three resources it owns (the
`attenddance-checklist` DynamoDB table, Lambda function, and its execution
role).

**One-time, from a session with IAM admin rights** (console, CloudShell, or a
profile that can manage IAM):
```
./bootstrap-iam.sh                        # uses your currently-active AWS session
./bootstrap-iam.sh --profile some-admin-profile   # or a named admin profile
```
This creates the `attenddance-checklist-deploy` IAM user, attaches the
least-privilege policy in `deploy-iam-policy.json`, and prints a one-time
access key. Copy it and run:
```
aws configure --profile attenddance-checklist-deploy
```
(region: `us-east-1`). After that, `./deploy.sh` always uses this profile —
never `default` or any other project's credentials.

## Requirements to run `deploy.sh`

- The `attenddance-checklist-deploy` profile configured as above.
- `zip` and `python3` (with `boto3` installed — `pip install boto3` if needed).
