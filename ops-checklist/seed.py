"""Idempotent seed script for the fall go-live checklist. Safe to re-run any
time — only inserts items whose item_id doesn't already exist; never touches
an existing row's done state. Run standalone (`python3 seed.py`) or let
deploy.sh call it automatically after every deploy.

To add a new item later: append a tuple to ITEMS below and re-run this script.
No frontend changes needed.
"""

from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

TABLE_NAME = "attenddance-checklist"
LIST_ID = "fall-golive-2026"

ITEMS = [
    ("01", "Close out summer classes",
     "Classes page → Cancel Class on anything summer-only. Auto-stops recurring "
     "tuition charges + clears the waitlist. Leave anything running into fall alone."),
    ("02", "Build the fall schedule",
     "Classes page → Add Class for each fall class (day/time/instructor/max size "
     "— caps are enforced). Then Payments page → one recurring charge per class "
     "(amount, category 'tuition', day it bills). Safe to set up early — won't "
     "charge anyone until the first real due date after creation."),
    ("03", "Open registration",
     "Enrollment page → flip 'Registration open,' then share the link "
     "(attenddance.fly.dev/register). Returning families use the same link — "
     "system matches by email, no duplicates, auto re-enrolls existing dancers."),
    ("04", "Approve registrations as they come in",
     "Enrollment page shows a badge when new ones arrive. Approving creates the "
     "family + enrolls the kids. Flags 'Returning' on matches to an existing family."),
    ("05", "Set up parent portal access",
     "On a dancer's page → 'Portal Access' card. Generate invite codes for new "
     "parents. Locked-out parent? Make them a reset link right there — texts to "
     "them, expires in an hour."),
    ("06", "First week: check-in on tablet",
     "Take Attendance page, tablet or laptop — teachers have access. RFID readers "
     "do NOT work with this system — don't plug in the old Pi setup. Card-tap is "
     "buildable later if wanted."),
    ("07", "First billing cycle",
     "Tuition posts automatically on each class's due date. Mid-month joiners are "
     "NOT auto-charged that partial month — post it manually from the Payments page."),
    ("08", "Send Thomas the Gmail app password",
     "Unlocks auto-sending receipts/reminders/blasts. Last thing blocking email."),
]


def main():
    # Explicit profile — without this, boto3 silently falls back to `default`
    # (a different project's deploy identity with no access to this table).
    session = boto3.Session(profile_name="attenddance-checklist-deploy")
    ddb = session.resource("dynamodb", region_name="us-east-1")
    table = ddb.Table(TABLE_NAME)
    now = datetime.now(timezone.utc).isoformat()

    for idx, (item_id, title, note) in enumerate(ITEMS, start=1):
        try:
            table.put_item(
                Item={
                    "list_id": LIST_ID,
                    "item_id": item_id,
                    "sort_order": idx,
                    "title": title,
                    "note": note,
                    "done": False,
                    "done_by": "",
                    "done_at": "",
                    "created_at": now,
                    "updated_at": now,
                },
                ConditionExpression="attribute_not_exists(item_id)",
            )
            print(f"  created {item_id}: {title}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                print(f"  skipped {item_id} (already exists): {title}")
            else:
                raise


if __name__ == "__main__":
    main()
