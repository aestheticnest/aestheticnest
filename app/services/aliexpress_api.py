"""Small AliExpress Affiliate Open Platform client using the signed TOP gateway."""
import hashlib
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests


class AliExpressAPIError(RuntimeError):
    pass


class AliExpressClient:
    def __init__(self, app_key, app_secret, tracking_id, endpoint, session_token=""):
        self.app_key = app_key
        self.app_secret = app_secret
        self.tracking_id = tracking_id
        self.endpoint = endpoint
        self.session_token = session_token

    @property
    def configured(self):
        return bool(self.app_key and self.app_secret and self.tracking_id and self.endpoint)

    def _call(self, method, arguments):
        if not self.configured:
            raise AliExpressAPIError("AliExpress API credentials are not configured.")
        params = {
            "app_key": self.app_key,
            "method": method,
            "timestamp": datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S"),
            "format": "json",
            "v": "2.0",
            "sign_method": "md5",
            **arguments,
        }
        if self.session_token:
            params["session"] = self.session_token
        canonical = "".join(f"{key}{params[key]}" for key in sorted(params))
        params["sign"] = hashlib.md5((self.app_secret + canonical + self.app_secret).encode()).hexdigest().upper()
        try:
            response = requests.post(self.endpoint, data=params, timeout=(5, 20))
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise AliExpressAPIError("AliExpress could not be reached. Check the API endpoint and credentials.") from exc
        if not isinstance(data, dict) or "error_response" in data:
            raise AliExpressAPIError("AliExpress rejected the request or returned an unexpected response.")
        return data

    @staticmethod
    def _find_key(node, wanted):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in wanted:
                    if isinstance(value, (list, dict)):
                        return value
                    if isinstance(value, str):
                        return [value]
                found = AliExpressClient._find_key(value, wanted)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = AliExpressClient._find_key(value, wanted)
                if found is not None:
                    return found
        return None

    def _normalize_products(self, data, min_commission=0):
        rows = self._find_key(data, {"products", "product_list", "product"}) or []
        if isinstance(rows, dict):
            rows = rows.get("product", [rows])
        if isinstance(rows, dict):
            rows = [rows]
        products = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                rate = float(str(row.get("commission_rate", "0")).rstrip("%"))
            except (ValueError, TypeError):
                rate = 0.0
            if rate < float(min_commission or 0):
                continue
            raw_url = str(row.get("promotion_link") or row.get("product_detail_url") or "")
            stock = next((row[key] for key in ("stock_quantity", "product_stock", "quantity_available") if row.get(key) is not None), None)
            products.append({
                "title": str(row.get("product_title", ""))[:180],
                "item_id": str(row.get("product_id", "")),
                "url": raw_url.replace("http://", "https://", 1),
                "image": str(row.get("product_main_image_url", "")),
                "price": self._price(row.get("app_sale_price") or row.get("sale_price")),
                "commission_rate": rate,
                "stock_quantity": stock,
            })
        return products

    def search_products(self, keyword, page=1, category_id=None, min_commission=0):
        args = {
            "keywords": keyword[:100], "page_no": max(1, int(page)), "page_size": 20,
            "tracking_id": self.tracking_id, "target_currency": "USD", "target_language": "EN",
            "ship_to_country": "US",
            "fields": "product_id,product_title,product_detail_url,product_main_image_url,sale_price,app_sale_price,commission_rate,promotion_link",
        }
        if category_id:
            args["category_ids"] = str(category_id)
        return self._normalize_products(self._call("aliexpress.affiliate.product.query", args), min_commission)

    def search_hot_products(self, page=1, category_id=None, min_commission=0):
        args = {
            "page_no": max(1, int(page)), "page_size": 20, "tracking_id": self.tracking_id,
            "target_currency": "USD", "target_language": "EN", "ship_to_country": "US",
            "fields": "product_id,product_title,product_detail_url,product_main_image_url,sale_price,app_sale_price,commission_rate,promotion_link",
        }
        if category_id:
            args["category_ids"] = str(category_id)
        return self._normalize_products(self._call("aliexpress.affiliate.hotproduct.query", args), min_commission)

    @staticmethod
    def _price(value):
        try:
            return float(str(value).replace(",", ""))
        except (ValueError, TypeError):
            return 0.0

    def generate_tracking_link(self, product_url):
        parsed = urlparse(product_url)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (hostname == "aliexpress.com" or hostname.endswith(".aliexpress.com")):
            raise ValueError("Enter a full https://www.aliexpress.com product URL.")
        data = self._call("aliexpress.affiliate.link.generate", {
            "tracking_id": self.tracking_id,
            "promotion_link_type": 0,
            "source_values": product_url,
        })
        links = self._find_key(data, {"promotion_links", "promotion_link"})
        if links:
            entry = links[0]
            value = entry.get("promotion_link") if isinstance(entry, dict) else entry
            if value:
                return str(value).replace("http://", "https://", 1)
        raise AliExpressAPIError("No tracking link was returned for this product.")

    def sync_product(self, item_id):
        matches = self.search_products(str(item_id))
        return next((item for item in matches if item["item_id"] == str(item_id)), None)


def client_from_config(config):
    return AliExpressClient(
        config.get("ALIEXPRESS_APP_KEY", ""), config.get("ALIEXPRESS_APP_SECRET", ""),
        config.get("ALIEXPRESS_TRACKING_ID", ""), config.get("ALIEXPRESS_API_URL", ""),
        config.get("ALIEXPRESS_SESSION", ""),
    )
