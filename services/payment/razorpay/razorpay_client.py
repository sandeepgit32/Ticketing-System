"""
Razorpay SDK wrapper
====================
Thin functions around the official razorpay Python SDK so that the rest of
the service never imports the SDK directly.  Each function can be tested in
isolation by supplying a real or mocked client.
"""

import razorpay
from razorpay.errors import SignatureVerificationError


def create_razorpay_client(key_id: str, key_secret: str) -> razorpay.Client:
    """Return an authenticated Razorpay SDK client."""
    return razorpay.Client(auth=(key_id, key_secret))


def create_order(client: razorpay.Client, amount_inr: float, receipt: str) -> dict:
    """Create a Razorpay order and return the raw order dict.

    Args:
        client:     Authenticated Razorpay client.
        amount_inr: Amount in Indian Rupees.  Converted to paise (×100)
                    internally before being sent to Razorpay.
        receipt:    Caller-supplied receipt ID (e.g. reservation UUID, max 40
                    chars).  Stored on the order so the fallback webhook path
                    can map back to the internal intent_id.

    Returns:
        The Razorpay order dict (contains at least ``id``, ``amount``,
        ``currency``, ``receipt``, ``status``).

    Raises:
        razorpay.errors.BadRequestError: If any required field is invalid.
        Exception: For network or other SDK errors.
    """
    return client.order.create(
        {
            "amount": int(amount_inr * 100),  # paise
            "currency": "INR",
            "receipt": receipt[:40],  # Razorpay receipt max length is 40
        }
    )


def verify_payment_signature(
    client: razorpay.Client,
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> bool:
    """Verify the HMAC-SHA256 signature returned by Razorpay Checkout to the frontend.

    The SDK computes ``HMAC-SHA256(order_id + "|" + payment_id, key_secret)``
    and raises ``SignatureVerificationError`` when it does not match the
    provided signature.

    Args:
        client:               Authenticated Razorpay client (uses its key_secret).
        razorpay_order_id:    Razorpay order ID (e.g. ``order_ABC123``).
        razorpay_payment_id:  Razorpay payment ID (e.g. ``pay_XYZ456``).
        razorpay_signature:   Signature string returned by Razorpay Checkout.

    Returns:
        ``True`` if the signature is valid, ``False`` otherwise.
    """
    try:
        client.utility.verify_payment_signature(
            {
                "razorpay_order_id": razorpay_order_id,
                "razorpay_payment_id": razorpay_payment_id,
                "razorpay_signature": razorpay_signature,
            }
        )
        return True
    except SignatureVerificationError:
        return False


def verify_webhook_signature(body: bytes, signature: str, webhook_secret: str) -> bool:
    """Verify the HMAC-SHA256 signature on a Razorpay inbound webhook.

    Razorpay signs the raw request body with the webhook secret configured in
    the Dashboard and sends the hex digest in the ``X-Razorpay-Signature``
    header.  This function recomputes the digest and performs a constant-time
    comparison.

    Note: this function intentionally does not take a ``razorpay.Client``
    because the webhook secret is separate from the API key secret and does
    not require an authenticated client instance.

    Args:
        body:           Raw request body bytes.
        signature:      Value of the ``X-Razorpay-Signature`` header.
        webhook_secret: Razorpay webhook secret from the Dashboard.

    Returns:
        ``True`` if the signature is valid, ``False`` otherwise.
    """
    import hashlib
    import hmac as hmac_module

    expected = hmac_module.new(
        webhook_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac_module.compare_digest(expected, signature)
