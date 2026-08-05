"""Loads the configurable standard-product list (currently A/B, extensible to C/D/...).

Re-reads the JSON file on every call rather than caching in memory. At POC scale
(a handful of products) this is negligible overhead, and it means an operator can
edit standard_products.json and see the change on the very next request with no
server restart -- important since the real A/B numbers aren't known yet.
"""

import json

import config


def load_products():
    with open(config.STANDARD_PRODUCTS_PATH, "r", encoding="utf-8") as f:
        products = json.load(f)
    for p in products:
        required = {"id", "name", "length_cm", "width_cm", "area_cm2"}
        missing = required - p.keys()
        if missing:
            raise ValueError(f"standard_products.json entry {p} missing fields: {missing}")
    return products


def get_product(product_id):
    for p in load_products():
        if p["id"] == product_id:
            return p
    return None
