import smtplib
from email.message import EmailMessage

import stripe
from flask import current_app, url_for


def stripe_checkout(order):
    if not current_app.config.get("STRIPE_SECRET_KEY"):
        return None
    stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]
    items = [{
        "price_data": {
            "currency": order.currency.lower(),
            "product_data": {"name": item.product_title, "metadata": {"sku": item.sku}},
            "unit_amount": int(item.unit_price * 100),
        },
        "quantity": item.quantity,
    } for item in order.items]
    session = stripe.checkout.Session.create(
        mode="payment", line_items=items, customer_email=order.email,
        success_url=url_for("checkout.payment_success", public_id=order.public_id, _external=True) + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=url_for("checkout.payment_cancel", public_id=order.public_id, _external=True),
        client_reference_id=order.public_id, metadata={"order_id": order.public_id},
    )
    return session


def send_order_email(order):
    cfg = current_app.config
    if not all((cfg.get("MAIL_SERVER"), cfg.get("MAIL_DEFAULT_SENDER"))):
        return False
    message = EmailMessage()
    message["Subject"] = f"Order received · {order.public_id[:8].upper()}"
    message["From"] = cfg["MAIL_DEFAULT_SENDER"]
    message["To"] = order.email
    details = "\n".join(f"{item.quantity} × {item.product_title} — {order.currency} {item.unit_price:.2f}" for item in order.items)
    message.set_content(
        f"Hello {order.customer_name},\n\nWe received your order {order.public_id[:8].upper()}. "
        f"Payment status: {order.payment_status}.\n\n{details}\n\n"
        f"Total: {order.currency} {order.total_amount:.2f}\n\nAesthetic Nest"
    )
    try:
        with smtplib.SMTP(cfg["MAIL_SERVER"], cfg.get("MAIL_PORT", 587), timeout=15) as smtp:
            if cfg.get("MAIL_USE_TLS"):
                smtp.starttls()
            if cfg.get("MAIL_USERNAME"):
                smtp.login(cfg["MAIL_USERNAME"], cfg.get("MAIL_PASSWORD", ""))
            smtp.send_message(message)
        return True
    except (OSError, smtplib.SMTPException):
        current_app.logger.exception("Order confirmation email failed for order %s", order.public_id)
        return False
