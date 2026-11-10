from urllib.parse import urlparse

from flask import Blueprint, abort, current_app, redirect, request

from app import db
from app.models import AffiliateClick, Product

affiliate_bp = Blueprint("affiliate", __name__, url_prefix="/affiliate")


@affiliate_bp.get("/redirect/<int:product_id>")
def redirect_product(product_id):
    product = Product.query.filter_by(id=product_id, is_active=True, is_affiliate=True).first_or_404()
    destination = product.affiliate_url or ""
    parsed = urlparse(destination)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (hostname == "aliexpress.com" or hostname.endswith(".aliexpress.com")):
        abort(404)
    click = AffiliateClick(
        product_id=product.id,
        user_agent=(request.user_agent.string or "")[:512],
        referrer=(request.referrer or "")[:2048],
        destination_url=destination,
    )
    db.session.add(click)
    db.session.commit()
    return redirect(destination, code=302)
