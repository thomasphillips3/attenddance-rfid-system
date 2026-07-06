"""Lambda handler for the fall go-live checklist. Two routes over a Function
URL (payload-format 2.0): GET /items lists the checklist, POST /toggle flips
one item's done state. No auth — the security model is an unlisted URL; this
table never holds PII or financial data.
"""

import json
import os
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

TABLE_NAME = os.environ.get("TABLE_NAME", "attenddance-checklist")
LIST_ID = "fall-golive-2026"
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")

ddb = boto3.resource("dynamodb")
table = ddb.Table(TABLE_NAME)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "content-type",
    "Content-Type": "application/json",
}


def handler(event, context):
    method = event["requestContext"]["http"]["method"]
    path = event["requestContext"]["http"]["path"]

    if method == "OPTIONS":
        return _resp(200, {})
    if method == "GET" and path == "/items":
        return _list_items()
    if method == "POST" and path == "/toggle":
        try:
            body = json.loads(event.get("body") or "{}")
        except (TypeError, ValueError):
            return _resp(400, {"error": "invalid JSON body"})
        return _toggle_item(body)

    return _resp(404, {"error": "not found"})


def _list_items():
    resp = table.query(KeyConditionExpression=Key("list_id").eq(LIST_ID))
    items = sorted(resp.get("Items", []), key=lambda i: int(i["sort_order"]))
    return _resp(200, {"items": items})


def _toggle_item(body):
    item_id = body.get("item_id")
    if not item_id:
        return _resp(400, {"error": "item_id is required"})
    done = bool(body.get("done"))
    done_by = (body.get("done_by") or "").strip() if done else ""
    now = datetime.now(timezone.utc).isoformat()

    table.update_item(
        Key={"list_id": LIST_ID, "item_id": item_id},
        UpdateExpression="SET done = :d, done_by = :by, done_at = :at, updated_at = :now",
        ExpressionAttributeValues={
            ":d": done,
            ":by": done_by,
            ":at": now if done else "",
            ":now": now,
        },
    )
    return _resp(200, {"ok": True})


def _resp(status, body_dict):
    return {
        "statusCode": status,
        "headers": CORS_HEADERS,
        "body": json.dumps(body_dict, default=str),
    }
