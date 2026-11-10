# Aesthetic Nest

A Flask storefront with separate native-checkout and AliExpress affiliate catalogs, owner-only studio routes, click attribution, and a Stripe Checkout integration that confirms card payment only through a signed webhook.

## Start on Zorin OS

From this project folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` before the first run. Set a long random `SECRET_KEY`, choose a private `ADMIN_SECRET_ROUTE`, and set a one-time random `ADMIN_BOOTSTRAP_KEY`. For a local HTTP run set `FLASK_ENV=development` and `SESSION_COOKIE_SECURE=false`. Keep secure cookies enabled behind HTTPS in production.

Generate secret values with `python -c 'import secrets; print(secrets.token_hex(32))'` and keep each key private.

```bash
flask --app wsgi db upgrade
python run.py
```

Open `http://127.0.0.1:5000`. The SQLite database and its tables are created at `instance/database.sqlite` by the initial migration. Create your first owner account at `/<ADMIN_SECRET_ROUTE>/bootstrap`; remove `ADMIN_BOOTSTRAP_KEY` from `.env` immediately after setup. The default secret path is `/admin_secret_99812`; change it before deployment. `/admin` redirects to the storefront.

For a production WSGI server, put the app behind an HTTPS reverse proxy and run:

```bash
gunicorn --workers 3 --bind 127.0.0.1:8000 wsgi:app
```

## Store setup

- Create native products in the private studio panel. A native item is purchasable only while it is published and has a positive owner-confirmed stock count. The application does not pretend to own AliExpress inventory or auto-place supplier orders.
- Add AliExpress Affiliate Open Platform credentials and the publisher tracking ID to `.env` to enable live search and tracking-link generation. Imported results are drafts and must be reviewed and published by the owner.
- Configure Stripe `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY` and `STRIPE_WEBHOOK_SECRET` to expose card checkout. Point the Stripe webhook to `/checkout/stripe-webhook` and enable `checkout.session.completed` and `checkout.session.expired`. Cash on delivery is available by default and can be disabled with `ENABLE_CASH_ON_DELIVERY=false`.
- Configure SMTP values in `.env` for order email. Order placement and payment state are persisted even if email delivery is not configured; email sending failures are logged.
- Rate limits use local memory by default. For a multi-worker deployment, set `RATELIMIT_STORAGE_URI` to a private Redis URL so limits are shared between workers.

## Catalog integrity

There is no seed catalog of invented products, supplier stock counts, prices, photos, or affiliate URLs. The storefront starts empty; populate it from products you can actually source or from current API results. This keeps live prices, attribution, inventory and shipping representations under the store owner's control.

## Security notes

All browser POST routes use Flask-WTF CSRF protection. Stripe webhooks verify their signature instead of using browser CSRF. Admin entry points require an owner/admin role; failed or anonymous access redirects to the storefront. Passwords use Werkzeug scrypt hashes, checkout stock is rechecked at order placement, and payment status is not changed to paid from a browser return URL. Set `SECRET_KEY`, bootstrap key, SMTP credentials and payment/API secrets only in the server's private `.env` or secret manager.
