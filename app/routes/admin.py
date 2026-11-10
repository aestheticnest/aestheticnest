import re
import secrets
import math
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy import func

from app import db, limiter
from app.models import AffiliateClick, Order, Product, User
from app.security import admin_required
from app.services.aliexpress_api import AliExpressAPIError, client_from_config

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin.dashboard"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()[:254]
        user = User.query.filter_by(email=email, is_active=True).first()
        if user and user.check_password(request.form.get("password", "")) and user.role in {"owner", "admin"}:
            login_user(user, remember=False, fresh=True)
            return redirect(url_for("admin.dashboard"))
        flash("Sign-in failed.", "error")
    return render_template("admin/login.html", bootstrap_allowed=not User.query.first() and bool(current_app.config["ADMIN_BOOTSTRAP_KEY"]))


@admin_bp.route("/bootstrap", methods=["GET", "POST"])
@limiter.limit("3 per hour", methods=["POST"])
def bootstrap():
    if User.query.first() or not current_app.config.get("ADMIN_BOOTSTRAP_KEY"):
        abort(404)
    if request.method == "POST":
        supplied = request.form.get("bootstrap_key", "")
        expected = current_app.config["ADMIN_BOOTSTRAP_KEY"]
        if not secrets.compare_digest(supplied, expected):
            flash("Bootstrap key was not accepted.", "error")
        else:
            email = (request.form.get("email") or "").strip().lower()[:254]
            password = request.form.get("password", "")
            if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(password) < 14:
                flash("Use a valid email and a password of at least 14 characters.", "error")
            else:
                user = User(email=email, role="owner")
                user.set_password(password)
                db.session.add(user)
                db.session.commit()
                login_user(user, fresh=True)
                flash("Owner account created. Remove the bootstrap key from your .env file now.", "success")
                return redirect(url_for("admin.dashboard"))
    return render_template("admin/bootstrap.html")


@admin_bp.post("/logout")
@admin_required
def logout():
    logout_user()
    return redirect(url_for("main.home"))


@admin_bp.get("/")
@admin_required
def dashboard():
    revenue = db.session.query(func.coalesce(func.sum(Order.total_amount), 0)).filter(Order.payment_status == "paid").scalar()
    pending = Order.query.filter_by(payment_status="pending").count()
    clicks = AffiliateClick.query.count()
    products = Product.query.count()
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(6).all()
    return render_template("admin/dashboard.html", revenue=revenue, pending=pending, clicks=clicks, products=products, recent_orders=recent_orders)


def parse_product_form(form, product=None):
    title = " ".join((form.get("title") or "").split())[:180]
    description = (form.get("description") or "").strip()[:12000]
    category = (form.get("category") or "").strip()[:80]
    allowed = {"Home & Living", "Smart Lighting", "Workspace", "Kitchen & Coffee"}
    if not title or not description or category not in allowed:
        raise ValueError("Enter a title, description, and one of the listed categories.")
    try:
        price = Decimal(form.get("price", ""))
        compare = Decimal(form["compare_at_price"]) if form.get("compare_at_price", "").strip() else None
        stock = int(form.get("stock_quantity", "0"))
    except (InvalidOperation, ValueError):
        raise ValueError("Price and stock must be valid numbers.")
    if not price.is_finite() or (compare is not None and not compare.is_finite()) or price <= 0 or price > 1000000 or (compare is not None and compare < price) or stock < 0 or stock > 1000000:
        raise ValueError("Price must be positive, compare price must be higher, and stock cannot be negative.")
    affiliate = form.get("is_affiliate") == "1"
    affiliate_url = (form.get("affiliate_url") or "").strip()[:2048] or None
    item_id = (form.get("aliexpress_item_id") or "").strip()[:80] or None
    if affiliate:
        if not affiliate_url:
            raise ValueError("Affiliate products need an AliExpress product URL.")
        from urllib.parse import urlparse
        parsed = urlparse(affiliate_url)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (hostname == "aliexpress.com" or hostname.endswith(".aliexpress.com")):
            raise ValueError("Affiliate URLs must point to AliExpress over HTTPS.")
        link = client_from_config(current_app.config)
        if link.configured:
            try:
                affiliate_url = link.generate_tracking_link(affiliate_url)
            except (AliExpressAPIError, ValueError) as exc:
                raise ValueError(str(exc)) from exc
    images = []
    for raw in (form.get("images") or "").splitlines():
        url = raw.strip()
        if not url:
            continue
        if not url.startswith("https://") or len(url) > 2048:
            raise ValueError("Every image needs to be an https URL.")
        images.append(url)
    if len(images) > 8:
        raise ValueError("Add no more than 8 images.")
    if product is None:
        product = Product(title=title, description=description, category=category)
    product.title, product.description, product.category = title, description, category
    product.price, product.compare_at_price, product.stock_quantity = price, compare, stock
    product.is_affiliate, product.affiliate_url, product.aliexpress_item_id = affiliate, affiliate_url, item_id
    try:
        rate = float(form.get("commission_rate", "0") or 0)
        if not math.isfinite(rate):
            raise ValueError("Commission rate must be a number.")
        product.commission_rate = max(0, min(rate, 100))
    except ValueError:
        raise ValueError("Commission rate must be a number.")
    product.images = images
    product.is_featured = form.get("is_featured") == "1"
    product.is_active = form.get("is_active") == "1"
    if not product.slug:
        base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:170] or secrets.token_hex(6)
        slug = base
        suffix = 2
        while Product.query.filter_by(slug=slug).first():
            slug = f"{base}-{suffix}"
            suffix += 1
        product.slug = slug
    if not product.sku:
        product.sku = f"AN-{secrets.token_hex(5).upper()}"
    return product


@admin_bp.route("/products", methods=["GET", "POST"])
@admin_required
def products_manage():
    if request.method == "POST":
        try:
            product = parse_product_form(request.form)
            db.session.add(product)
            db.session.commit()
            flash("Product saved.", "success")
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "error")
            return render_template("admin/products_manage.html", products=Product.query.order_by(Product.created_at.desc()).all(), edit_product=None), 400
        return redirect(url_for("admin.products_manage"))
    return render_template("admin/products_manage.html", products=Product.query.order_by(Product.created_at.desc()).all(), edit_product=None)


@admin_bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def product_edit(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == "POST":
        try:
            product = parse_product_form(request.form, product)
            db.session.commit()
            flash("Product updated.", "success")
            return redirect(url_for("admin.products_manage"))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template("admin/products_manage.html", products=Product.query.order_by(Product.created_at.desc()).all(), edit_product=product)


@admin_bp.post("/products/<int:product_id>/delete")
@admin_required
def product_delete(product_id):
    product = Product.query.get_or_404(product_id)
    if product.order_items:
        product.is_active = False
        db.session.commit()
        flash("This product appears in an order, so it was archived.", "success")
    else:
        db.session.delete(product)
        db.session.commit()
        flash("Product removed.", "success")
    return redirect(url_for("admin.products_manage"))


@admin_bp.post("/products/<int:product_id>/sync")
@admin_required
def product_sync(product_id):
    product = Product.query.get_or_404(product_id)
    if not product.is_affiliate or not product.aliexpress_item_id:
        flash("Only affiliate items with an AliExpress item ID can sync.", "error")
        return redirect(url_for("admin.products_manage"))
    try:
        latest = client_from_config(current_app.config).sync_product(product.aliexpress_item_id)
    except AliExpressAPIError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin.products_manage"))
    if not latest or latest["price"] <= 0:
        flash("AliExpress did not return a current listing for this item.", "error")
        return redirect(url_for("admin.products_manage"))
    product.price = Decimal(str(latest["price"]))
    product.commission_rate = latest["commission_rate"]
    product.affiliate_url = latest["url"] or product.affiliate_url
    if latest["image"].startswith("https://"):
        product.images = [latest["image"], *(product.images or [])[1:7]]
    if latest.get("stock_quantity") is not None:
        try:
            product.stock_quantity = max(0, int(latest["stock_quantity"]))
        except (TypeError, ValueError):
            pass
    db.session.commit()
    flash("AliExpress listing details synced. Confirm live stock manually before publishing.", "success")
    return redirect(url_for("admin.products_manage"))


@admin_bp.get("/orders")
@admin_required
def orders_manage():
    orders = Order.query.order_by(Order.created_at.desc()).limit(200).all()
    return render_template("admin/orders_manage.html", orders=orders)


@admin_bp.get("/orders/<int:order_id>/packing-slip")
@admin_required
def packing_slip(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template("admin/packing_slip.html", order=order)


@admin_bp.post("/orders/<int:order_id>/status")
@admin_required
def order_status(order_id):
    order = Order.query.get_or_404(order_id)
    status = request.form.get("status", "")
    tracking = " ".join((request.form.get("tracking_number") or "").split())[:100]
    if status not in {"pending", "paid", "shipped", "cancelled"}:
        abort(400)
    if status == "shipped":
        if order.payment_status not in {"paid", "pending"}:
            flash("Cancelled orders cannot ship.", "error")
            return redirect(url_for("admin.orders_manage"))
        if order.payment_provider == "stripe" and order.payment_status != "paid":
            flash("Wait for Stripe to confirm payment before shipping this order.", "error")
            return redirect(url_for("admin.orders_manage"))
        order.fulfillment_status = "shipped"
        order.tracking_number = tracking or None
    elif status == "cancelled":
        if order.payment_provider == "stripe" and order.payment_status == "pending":
            flash("This card session must expire before its reserved stock can be released.", "error")
            return redirect(url_for("admin.orders_manage"))
        if order.payment_status == "pending" and order.fulfillment_status != "shipped":
            for item in order.items:
                item.product.stock_quantity += item.quantity
            order.payment_status = "cancelled"
            order.fulfillment_status = "cancelled"
        else:
            flash("A paid order needs a refund before it can be cancelled here.", "error")
            return redirect(url_for("admin.orders_manage"))
    else:
        if status == "paid" and order.payment_provider == "stripe" and order.payment_status != "paid":
            flash("Stripe payments are confirmed by the signed webhook.", "error")
            return redirect(url_for("admin.orders_manage"))
        if status == "pending" and order.payment_status != "pending":
            flash("Payment status cannot be reset after it changes.", "error")
            return redirect(url_for("admin.orders_manage"))
        order.payment_status = status
    db.session.commit()
    flash("Order updated.", "success")
    return redirect(url_for("admin.orders_manage"))


@admin_bp.get("/settings")
@admin_required
def settings():
    api = client_from_config(current_app.config)
    stripe_ready = bool(current_app.config.get("STRIPE_SECRET_KEY") and current_app.config.get("STRIPE_WEBHOOK_SECRET"))
    return render_template("admin/settings.html", api_configured=api.configured, stripe_configured=stripe_ready, mail_configured=bool(current_app.config.get("MAIL_SERVER")))


@admin_bp.route("/import", methods=["GET", "POST"])
@admin_required
def import_products():
    results = []
    if request.method == "POST":
        client = client_from_config(current_app.config)
        keyword = " ".join((request.form.get("keyword") or "").split())[:100]
        try:
            minimum = float(request.form.get("min_commission", "0") or 0)
            category = request.form.get("category_id", "").strip()[:30] or None
            results = (
                client.search_hot_products(category_id=category, min_commission=minimum)
                if request.form.get("search_mode") == "hot"
                else client.search_products(keyword, category_id=category, min_commission=minimum)
            )
        except (ValueError, AliExpressAPIError) as exc:
            flash(str(exc), "error")
    return render_template("admin/import_products.html", results=results)


@admin_bp.post("/import/create")
@admin_required
def create_imported_product():
    title = " ".join((request.form.get("title") or "").split())[:180]
    url = request.form.get("url", "")[:2048]
    price = request.form.get("price", "")
    try:
        product = Product(
            title=title, slug="", description=title, price=Decimal(price), sku="",
            is_affiliate=True, affiliate_url=url, aliexpress_item_id=request.form.get("item_id", "")[:80] or None,
            commission_rate=float(request.form.get("commission_rate", "0") or 0), category="Home & Living",
            images=[request.form.get("image", "")[:2048]] if request.form.get("image", "").startswith("https://") else [],
            is_active=False,
        )
        if not title or product.price <= 0:
            raise ValueError("The imported product title and price are required.")
        base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:170]
        product.slug = f"{base}-{secrets.token_hex(3)}"
        product.sku = f"AN-{secrets.token_hex(5).upper()}"
        db.session.add(product)
        db.session.commit()
        flash("Imported product saved as an inactive draft. Review price, image, destination link and stock before publishing.", "success")
    except (ValueError, InvalidOperation) as exc:
        db.session.rollback()
        flash("Could not save this result: " + str(exc), "error")
    return redirect(url_for("admin.products_manage"))
