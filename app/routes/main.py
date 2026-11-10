from flask import Blueprint, abort, render_template, request
from sqlalchemy import or_

from app import db
from app.models import Product

main_bp = Blueprint("main", __name__)


@main_bp.get("/")
def home():
    products = Product.query.filter_by(is_active=True, is_affiliate=False).order_by(Product.is_featured.desc(), Product.created_at.desc()).limit(8).all()
    picks = Product.query.filter_by(is_active=True, is_affiliate=True).order_by(Product.is_featured.desc(), Product.created_at.desc()).limit(4).all()
    return render_template("index.html", products=products, picks=picks)


@main_bp.get("/shop")
def shop():
    category = request.args.get("category", "")[:80]
    query = request.args.get("q", "")[:100].strip()
    products_query = Product.query.filter_by(is_active=True, is_affiliate=False)
    if category:
        products_query = products_query.filter_by(category=category)
    if query:
        like = f"%{query}%"
        products_query = products_query.filter(or_(Product.title.ilike(like), Product.description.ilike(like)))
    products = products_query.order_by(Product.is_featured.desc(), Product.title.asc()).all()
    categories = [row[0] for row in db.session.query(Product.category).filter_by(is_active=True, is_affiliate=False).distinct().all()]
    return render_template("shop.html", products=products, categories=categories, category=category, query=query)


@main_bp.get("/products/<slug>")
def product_detail(slug):
    product = Product.query.filter_by(slug=slug, is_active=True, is_affiliate=False).first()
    if not product:
        abort(404)
    return render_template("product_detail.html", product=product)


@main_bp.get("/curated-finds")
def curated_finds():
    products = Product.query.filter_by(is_active=True, is_affiliate=True).order_by(Product.is_featured.desc(), Product.title.asc()).all()
    return render_template("curated_finds.html", products=products)
