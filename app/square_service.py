"""Square payment integration for AttenDANCE.

Creates invoices via the Square Invoices API so parents can pay online.
Targets the modern Square Python SDK (squareup >= 40), where the client is
``square.Square`` and calls return typed response objects (raising ``ApiError``
on failure) rather than the old ``Client`` / ``result.is_success()`` style.

Credentials come from Settings (DB, decrypted) first, falling back to env vars.
"""

import uuid

from flask import current_app


def get_access_token():
    """Square access token — from Settings (decrypted) first, env as fallback."""
    from app.crypto import decrypt
    from app.models import Setting
    stored = Setting.get('payments_square_access_token', '')
    if stored:
        return decrypt(stored)
    return current_app.config.get('SQUARE_ACCESS_TOKEN')


def get_location_id():
    """Square location id — from Settings first, env as fallback."""
    from app.models import Setting
    return Setting.get('payments_square_location_id', '') or current_app.config.get('SQUARE_LOCATION_ID')


def get_environment():
    """Square environment (sandbox/production) — Settings first, env as fallback."""
    from app.models import Setting
    return (Setting.get('payments_square_environment', '')
            or current_app.config.get('SQUARE_ENVIRONMENT', 'sandbox'))


def _client():
    """Build a configured Square client, or None if no token is set."""
    token = get_access_token()
    if not token:
        return None
    from square import Square
    from square.environment import SquareEnvironment
    env = SquareEnvironment.PRODUCTION if get_environment() == 'production' else SquareEnvironment.SANDBOX
    # Explicit timeout: the SDK passes None through to httpx, which DISABLES
    # timeouts — a hung Square API call would pin an admin request's worker
    # thread indefinitely (invoice send + test-connection run inline).
    return Square(token=token, environment=env, timeout=30)


def is_configured():
    """Check if Square credentials are set (token + location)."""
    return bool(get_access_token() and get_location_id())


def _error_detail(exc):
    """Pull a human-readable message out of a Square ApiError."""
    body = getattr(exc, 'body', None)
    if isinstance(body, dict):
        errors = body.get('errors') or []
        if errors and isinstance(errors[0], dict):
            return errors[0].get('detail') or errors[0].get('code') or str(body)
        return str(body)
    if isinstance(body, list) and body:
        first = body[0]
        if isinstance(first, dict):
            return first.get('detail') or first.get('code') or str(first)
    return str(body) if body else str(exc)


def test_connection():
    """Verify the configured Square credentials work.

    Returns (ok: bool, message: str).
    """
    client = _client()
    if not client:
        return False, "No access token configured."
    location_id = get_location_id()
    if not location_id:
        return False, "No location ID configured."
    from square.core.api_error import ApiError
    try:
        resp = client.locations.get(location_id=location_id)
        name = resp.location.name if getattr(resp, 'location', None) else location_id
        return True, f"Connected to '{name}' ({get_environment()})."
    except ApiError as e:
        return False, f"Square rejected the credentials: {_error_detail(e)}"
    except Exception as e:  # noqa: BLE001 — surface any SDK/network error to the admin
        return False, f"Connection failed: {e}"


def _find_or_create_customer(client, email, name):
    """Find an existing Square customer by email, or create one. Returns its id."""
    resp = client.customers.search(query={'filter': {'email_address': {'exact': email}}})
    customers = getattr(resp, 'customers', None) or []
    if customers:
        return customers[0].id

    parts = name.split(' ', 1)
    created = client.customers.create(
        idempotency_key=str(uuid.uuid4()),
        given_name=parts[0],
        family_name=parts[1] if len(parts) > 1 else '',
        email_address=email,
    )
    return created.customer.id


def send_invoice(student, amount_cents, line_items, due_date):
    """Create and publish a Square invoice for a student's outstanding balance.

    Args:
        student: Student model instance (needs parent_email/email and full_name).
        amount_cents: Total amount in cents (unused directly — line items drive it).
        line_items: list of dicts with 'name' and 'amount_cents'.
        due_date: date object for the payment due date.

    Returns:
        dict with invoice_id, invoice_url, status.
    """
    client = _client()
    if not client:
        raise Exception("Square is not configured. Set the access token and location ID in Settings.")

    location_id = get_location_id()
    email = student.parent_email or student.email
    if not email:
        raise Exception(f"No email address for {student.full_name}. Add a parent email or student email first.")

    from square.core.api_error import ApiError
    try:
        customer_id = _find_or_create_customer(client, email, student.full_name)

        order_line_items = [{
            'name': item['name'],
            'quantity': '1',
            'base_price_money': {'amount': item['amount_cents'], 'currency': 'USD'},
        } for item in line_items]

        order_resp = client.orders.create(
            order={
                'location_id': location_id,
                'customer_id': customer_id,
                'line_items': order_line_items,
            },
            idempotency_key=str(uuid.uuid4()),
        )
        order_id = order_resp.order.id

        invoice_resp = client.invoices.create(
            invoice={
                'location_id': location_id,
                'order_id': order_id,
                'primary_recipient': {'customer_id': customer_id},
                'payment_requests': [{
                    'request_type': 'BALANCE',
                    'due_date': due_date.isoformat(),
                    'automatic_payment_source': 'NONE',
                }],
                'delivery_method': 'EMAIL',
                'accepted_payment_methods': {
                    'card': True,
                    'square_gift_card': False,
                    'bank_account': True,
                    'buy_now_pay_later': False,
                    'cash_app_pay': True,
                },
                'title': f"LaShelle's School of Dance - {student.full_name}",
            },
            idempotency_key=str(uuid.uuid4()),
        )
        invoice = invoice_resp.invoice

        publish_resp = client.invoices.publish(
            invoice_id=invoice.id,
            version=invoice.version,
            idempotency_key=str(uuid.uuid4()),
        )
        published = publish_resp.invoice
        return {
            'invoice_id': published.id,
            'invoice_url': getattr(published, 'public_url', '') or '',
            'status': published.status,
        }
    except ApiError as e:
        raise Exception(f"Square error: {_error_detail(e)}") from e
