import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import stripe
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_wtf.csrf import validate_csrf
from wtforms.validators import ValidationError

from app import csrf, db, limiter
from app.models import Order, OrderItem, Product
from app.services.payment import send_order_email, stripe_checkout

checkout_bp = Blueprint("checkout", __name__)


def cart_items():
    cart = session.get("cart", {})
    if not isinstance(cart, dict):
        session["cart"] = {}
        return [], Decimal("0.00")
    ids = []
    for key in cart:
        if str(key).isdigit():
            ids.append(int(key))
    products = Product.query.filter(Product.id.in_(ids), Product.is_active.is_(True), Product.is_affiliate.is_(False)).all() if ids else []
    rows, total = [], Decimal("0.00")
    for product in products:
        try:
            quantity = max(1, min(int(cart.get(str(product.id), 1)), 20))
            price = Decimal(product.price)
        except (TypeError, ValueError, InvalidOperation):
            continue
        rows.append({"product": product, "quantity": quantity, "line_total": price * quantity})
        total += price * quantity
    return rows, total


@checkout_bp.get("/cart")
def cart():
    items, total = cart_items()
    return render_template("cart.html", items=items, total=total)


@checkout_bp.post("/cart/add/<int:product_id>")
def add_to_cart(product_id):
    product = Product.query.filter_by(id=product_id, is_active=True, is_affiliate=False).first_or_404()
    if product.stock_quantity < 1:
        flash("This piece is currently unavailable.", "error")
        return redirect(url_for("main.product_detail", slug=product.slug))
    cart_data = session.get("cart", {})
    try:
        quantity = int(request.form.get("quantity", "1"))
    except ValueError:
        quantity = 1
    quantity = max(1, min(quantity, 20))
    key = str(product.id)
    requested = int(cart_data.get(key, 0)) + quantity
    cart_data[key] = min(product.stock_quantity, 20, requested)
    if cart_data[key] < requested:
        flash("Your bag quantity was adjusted to the stock currently available.", "info")
    session["cart"] = cart_data
    session.modified = True
    flash(f"{product.title} added to your bag.", "success")
    if request.form.get("intent") == "buy":
        return redirect(url_for("checkout.checkout"))
    referrer = urlparse(request.referrer or "")
    safe_referrer = referrer.path if not referrer.netloc else ""
    return redirect(safe_referrer or url_for("main.product_detail", slug=product.slug))


@checkout_bp.post("/cart/update")
def update_cart():
    data = {}
    for key, raw in request.form.items():
        if key.startswith("quantity_") and key[9:].isdigit():
            try:
                qty = int(raw)
            except ValueError:
                continue
            if qty > 0:
                data[key[9:]] = min(qty, 20)
    session["cart"] = data
    flash("Your bag has been updated.", "success")
    return redirect(url_for("checkout.cart"))


@checkout_bp.get("/checkout")
def checkout():
    items, total = cart_items()
    if not items:
        flash("Add an in-stock item to your bag to continue.", "info")
        return redirect(url_for("checkout.cart"))
    available = bool(current_app.config.get("STRIPE_SECRET_KEY") and current_app.config.get("STRIPE_WEBHOOK_SECRET"))
    return render_template("checkout.html", items=items, total=total, stripe_available=available)


def clean(value, max_length):
    return " ".join((value or "").strip().split())[:max_length]


def validate_shipping(form):
    try:
        validate_csrf(form.get("csrf_token"))
    except ValidationError:
        return "Your checkout session expired. Please refresh and try again."
    required = ["customer_name", "email", "phone", "address_line1", "city", "region", "postal_code", "country"]
    if any(not clean(form.get(key), 254) for key in required):
        return "Complete all required delivery details."
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", clean(form.get("email"), 254)):
        return "Enter a valid email address."
    if len(clean(form.get("phone"), 40)) < 7 or len(clean(form.get("country"), 2)) != 2:
        return "Enter a valid phone number and two-letter country code."
    return None


@checkout_bp.post("/checkout")
@limiter.limit("5 per minute")
def submit_checkout():
    items, total = cart_items()
    if not items:
        return redirect(url_for("checkout.cart"))
    error = validate_shipping(request.form)
    if error:
        flash(error, "error")
        return redirect(url_for("checkout.checkout"))
    payment_method = request.form.get("payment_method", "")
    if payment_method not in {"cash_on_delivery", "stripe"}:
        flash("Choose an available payment method.", "error")
        return redirect(url_for("checkout.checkout"))
    if payment_method == "stripe" and not (current_app.config.get("STRIPE_SECRET_KEY") and current_app.config.get("STRIPE_WEBHOOK_SECRET")):
        flash("Online card payments are not configured yet. Choose cash on delivery.", "error")
        return redirect(url_for("checkout.checkout"))
    if payment_method == "cash_on_delivery" and not current_app.config.get("ENABLE_CASH_ON_DELIVERY", True):
        flash("That payment method is not available.", "error")
        return redirect(url_for("checkout.checkout"))

    order = Order(
        customer_name=clean(request.form.get("customer_name"), 160),
        email=clean(request.form.get("email"), 254).lower(),
        phone=clean(request.form.get("phone"), 40),
        address_line1=clean(request.form.get("address_line1"), 200),
        address_line2=clean(request.form.get("address_line2"), 200),
        city=clean(request.form.get("city"), 100), region=clean(request.form.get("region"), 100),
        postal_code=clean(request.form.get("postal_code"), 30),
        country=clean(request.form.get("country"), 2).upper(),
        payment_provider="stripe" if payment_method == "stripe" else "cash_on_delivery",
        total_amount=total, currency=current_app.config["STORE_CURRENCY"],
    )
    db.session.add(order)
    try:
        db.session.flush()
        for row in items:
            product = Product.query.filter_by(id=row["product"].id, is_active=True, is_affiliate=False).with_for_update().first()
            if not product or product.stock_quantity < row["quantity"]:
                raise ValueError(f"{row['product'].title} no longer has enough stock.")
            product.stock_quantity -= row["quantity"]
            db.session.add(OrderItem(
                order=order, product_id=product.id, product_title=product.title, sku=product.sku,
                quantity=row["quantity"], unit_price=product.price,
            ))
        db.session.flush()
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(url_for("checkout.cart"))
    if payment_method == "stripe":
        try:
            payment_session = stripe_checkout(order)
        except (stripe.StripeError, ValueError):
            current_app.logger.exception("Unable to create Stripe Checkout session")
            db.session.rollback()
            flash("Secure card checkout could not be started. Please try again.", "error")
            return redirect(url_for("checkout.checkout"))
        order.payment_reference = payment_session.id
        db.session.commit()
        return redirect(payment_session.url, code=303)
    db.session.commit()
    session["cart"] = {}
    send_order_email(order)
    return redirect(url_for("checkout.order_confirmation", public_id=order.public_id))


@checkout_bp.get("/orders/<public_id>")
def order_confirmation(public_id):
    order = Order.query.filter_by(public_id=public_id).first_or_404()
    return render_template("order_confirmation.html", order=order)


@checkout_bp.get("/checkout/success/<public_id>")
def payment_success(public_id):
    order = Order.query.filter_by(public_id=public_id).first_or_404()
    checkout_id = request.args.get("session_id", "")
    if order.payment_provider != "stripe" or checkout_id != order.payment_reference:
        abort(404)
    session["cart"] = {}
    return render_template("order_confirmation.html", order=order)


@checkout_bp.get("/checkout/cancelled/<public_id>")
def payment_cancel(public_id):
    Order.query.filter_by(public_id=public_id, payment_provider="stripe").first_or_404()
    flash("Card payment was cancelled. Your bag is ready if you want to try again.", "info")
    return redirect(url_for("checkout.cart"))


@checkout_bp.post("/checkout/stripe-webhook")
@csrf.exempt
def stripe_webhook():
    payload = request.get_data()
    signature = request.headers.get("Stripe-Signature", "")
    secret = current_app.config.get("STRIPE_WEBHOOK_SECRET")
    if not secret:
        abort(503)
    try:
        event = stripe.Webhook.construct_event(payload, signature, secret)
    except (ValueError, stripe.SignatureVerificationError):
        abort(400)
    if event["type"] == "checkout.session.completed":
        data = event["data"]["object"]
        public_id = (data.get("metadata") or {}).get("order_id")
        order = Order.query.filter_by(public_id=public_id, payment_status="pending", payment_provider="stripe").first()
        if order:
            order.payment_status = "paid"
            order.payment_reference = data.get("payment_intent") or order.payment_reference
            db.session.commit()
            send_order_email(order)
    elif event["type"] == "checkout.session.expired":
        data = event["data"]["object"]
        order = Order.query.filter_by(payment_reference=data.get("id"), payment_status="pending", payment_provider="stripe").first()
        if order:
            for item in order.items:
                item.product.stock_quantity += item.quantity
            order.payment_status = "cancelled"
            order.fulfillment_status = "cancelled"
            db.session.commit()
    return {"received": True}
