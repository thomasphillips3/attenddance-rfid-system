"""
Square payment integration for AttenDANCE.
Creates invoices via the Square Invoices API so parents can pay online.
"""

import uuid
from flask import current_app

def _get_client():
    """Get a configured Square API client, or None if not configured."""
    token = current_app.config.get('SQUARE_ACCESS_TOKEN')
    if not token:
        return None
    from square.client import Client
    return Client(
        access_token=token,
        environment=current_app.config.get('SQUARE_ENVIRONMENT', 'sandbox'),
    )

def is_configured():
    """Check if Square credentials are set."""
    return bool(current_app.config.get('SQUARE_ACCESS_TOKEN') and
                current_app.config.get('SQUARE_LOCATION_ID'))

def _find_or_create_customer(client, email, name):
    """Find existing Square customer by email or create one."""
    result = client.customers.search_customers(body={
        'query': {
            'filter': {
                'email_address': {'exact': email}
            }
        }
    })
    if result.is_success() and result.body.get('customers'):
        return result.body['customers'][0]['id']

    parts = name.split(' ', 1)
    result = client.customers.create_customer(body={
        'idempotency_key': str(uuid.uuid4()),
        'given_name': parts[0],
        'family_name': parts[1] if len(parts) > 1 else '',
        'email_address': email,
    })
    if result.is_success():
        return result.body['customer']['id']
    raise Exception(f"Failed to create Square customer: {result.errors}")

def send_invoice(student, amount_cents, line_items, due_date):
    """
    Create and publish a Square invoice for a student's outstanding balance.

    Args:
        student: Student model instance (needs parent_email and full_name)
        amount_cents: Total amount in cents (e.g. 15000 for $150.00)
        line_items: List of dicts with 'name' and 'amount_cents'
        due_date: date object for payment due date

    Returns:
        dict with invoice_id, invoice_url, status
    """
    client = _get_client()
    if not client:
        raise Exception("Square is not configured. Set SQUARE_ACCESS_TOKEN and SQUARE_LOCATION_ID.")

    location_id = current_app.config['SQUARE_LOCATION_ID']
    email = student.parent_email or student.email
    if not email:
        raise Exception(f"No email address for {student.full_name}. Add a parent email or student email first.")

    customer_id = _find_or_create_customer(client, email, student.full_name)

    order_line_items = []
    for item in line_items:
        order_line_items.append({
            'name': item['name'],
            'quantity': '1',
            'base_price_money': {
                'amount': item['amount_cents'],
                'currency': 'USD',
            },
        })

    order_result = client.orders.create_order(body={
        'order': {
            'location_id': location_id,
            'customer_id': customer_id,
            'line_items': order_line_items,
        },
        'idempotency_key': str(uuid.uuid4()),
    })
    if not order_result.is_success():
        raise Exception(f"Failed to create Square order: {order_result.errors}")
    order_id = order_result.body['order']['id']

    invoice_result = client.invoices.create_invoice(body={
        'invoice': {
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
        'idempotency_key': str(uuid.uuid4()),
    })
    if not invoice_result.is_success():
        raise Exception(f"Failed to create Square invoice: {invoice_result.errors}")

    invoice = invoice_result.body['invoice']
    invoice_id = invoice['id']
    version = invoice['version']

    publish_result = client.invoices.publish_invoice(
        invoice_id=invoice_id,
        body={'version': version, 'idempotency_key': str(uuid.uuid4())},
    )
    if not publish_result.is_success():
        raise Exception(f"Failed to publish Square invoice: {publish_result.errors}")

    published = publish_result.body['invoice']
    return {
        'invoice_id': published['id'],
        'invoice_url': published.get('public_url', ''),
        'status': published['status'],
    }
