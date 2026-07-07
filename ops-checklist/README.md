# Fall Go-Live Checklist

A tiny shared checklist for Wilkanda and Carollette to track AttenDANCE's fall
stand-up together, live, from their phones. Not part of the AttenDANCE app —
lives in this folder for convenience.

**Architecture:** a plain static page on S3 (no login, no AWS backend) backed
by a Google Sheet + Apps Script Web App for the shared/live state. Simpler
than a Lambda/DynamoDB backend, and dodges a real problem that one hit: some
ad-blockers and privacy DNS resolvers flag raw `*.lambda-url.*.on.aws`
domains as suspected trackers and silently fail the request. A
`script.google.com` URL doesn't have that problem.

## One-time setup: the Google Sheet + Apps Script backend

This part needs your own Google login — I can't do it headlessly.

1. Create a new Google Sheet (sheets.google.com → blank).
2. Rename the first tab to exactly `Checklist`.
3. Paste the contents of `sheet-seed-data.tsv` starting at cell A1 (select
   A1, then paste — Sheets will split it into columns automatically since
   it's tab-separated).
4. **Extensions → Apps Script.** Delete the default boilerplate code and
   paste in the contents of `Code.gs`.
5. **Deploy → New deployment.** Type: **Web app**. Execute as: **Me**. Who
   has access: **Anyone**. Click **Deploy**, authorize when prompted.
6. Copy the resulting URL (ends in `/exec`).

## Deploying the site

1. Open `deploy.sh` and set `APPS_SCRIPT_URL` at the top to the `/exec` URL
   from step 6 above.
2. Run `./deploy.sh`.

That's it — no AWS Lambda, no DynamoDB, no IAM roles. Just an S3 bucket
serving one HTML file.

## How it works

- One shared checklist (rows in the Google Sheet), no login.
- A **Simple / Detailed** toggle switches the whole page between short titles
  only and full instructions — same list, same data, just how much shows.
- Updates every ~15s and instantly on refocus, so both of them see each
  other's check-offs without doing anything.
- Checking something off writes directly to the Sheet — you can also just
  open the Sheet yourself and edit rows by hand if you ever want to.

## Adding a new item

Add a row to the `Checklist` sheet tab directly (any order — the page sorts
by the `sort_order` column). No redeploy needed; the page always reads live
from the Sheet.

## Redeploying after editing `index.html`

```
./deploy.sh
```
Safe to re-run any time — it just re-uploads the static files.

## Updating the Apps Script backend

If you ever edit `Code.gs`: paste the new version into the Apps Script editor
(Extensions → Apps Script on the Sheet), then **Deploy → Manage deployments**
→ edit the existing deployment → **Deploy** (this keeps the same `/exec` URL,
so you won't need to update `deploy.sh` or redeploy the site).

## Requirements to run `deploy.sh`

- AWS CLI configured with a profile that can create/write to an S3 bucket.
  Uses the `attenddance-checklist-deploy` profile by default (see
  `deploy.sh`) — a leftover name from an earlier AWS-backend version of this
  tool; any profile with S3 access works fine, it's just a bucket now.
