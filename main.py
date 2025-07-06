from flask import Flask, Response
import requests
import os
from datetime import datetime
import xml.etree.ElementTree as ET
import logging

app = Flask(__name__)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Config
API_URL = os.getenv("KEYCRM_API_URL", "https://openapi.keycrm.app/v1")
API_KEY = os.getenv("KEYCRM_API_KEY")
if not API_KEY:
    raise RuntimeError("KEYCRM_API_KEY is not set in environment.")

HEADERS = {"Authorization": f"Bearer {API_KEY}"}


# === Fetch all products with pagination ===
def fetch_all_products():
    products = []
    page = 1
    while True:
        response = requests.get(f"{API_URL}/products?page={page}", headers=HEADERS)
        data = response.json()
        page_data = data.get("data", [])
        if not page_data:
            break
        products.extend(page_data)
        logger.info(f"Fetched page {page} with {len(page_data)} products")
        if not data.get("next_page_url"):
            break
        page += 1
    return products


# === Fetch all offers for a given product ===
def fetch_offers_for_product(product_id):
    offers = []
    page = 1
    while True:
        response = requests.get(f"{API_URL}/products/{product_id}/offers?page={page}", headers=HEADERS)
        data = response.json()
        page_data = data.get("data", [])
        if not page_data:
            break
        offers.extend(page_data)
        if not data.get("next_page_url"):
            break
        page += 1
    return offers


# === Generate XML feed ===
def generate_rozetka_feed():
    products = fetch_all_products()

    root = ET.Element("yml_catalog", date=datetime.now().strftime("%Y-%m-%d %H:%M"))
    shop = ET.SubElement(root, "shop")
    ET.SubElement(shop, "name").text = "Znana"
    ET.SubElement(shop, "company").text = "Znana"
    ET.SubElement(shop, "url").text = "https://yourshop.ua"

    currencies = ET.SubElement(shop, "currencies")
    ET.SubElement(currencies, "currency", id="UAH", rate="1")

    categories = ET.SubElement(shop, "categories")
    ET.SubElement(categories, "category", id="1").text = "Жіночий одяг"

    offers_el = ET.SubElement(shop, "offers")

    for product in products:
        product_id = product["id"]
        name = product.get("name", "Unnamed Product")
        description = product.get("description", "")
        category_id = str(product.get("category_id", 1))
        currency = product.get("currency_code", "UAH")
        product_url = f"https://yourshop.ua/products/{product_id}"
        product_pic = product.get("thumbnail_url", "")

        variants = fetch_offers_for_product(product_id)
        for variant in variants:
            offer = ET.SubElement(offers_el, "offer", id=str(variant["id"]), available="true")
            ET.SubElement(offer, "url").text = product_url
            ET.SubElement(offer, "price").text = str(variant.get("price", 0))
            ET.SubElement(offer, "currencyId").text = currency
            ET.SubElement(offer, "categoryId").text = category_id
            ET.SubElement(offer, "picture").text = variant.get("thumbnail_url", product_pic)
            ET.SubElement(offer, "name").text = name
            ET.SubElement(offer, "description").text = description
            ET.SubElement(offer, "vendorCode").text = variant.get("sku", "")

            for prop in variant.get("properties", []):
                ET.SubElement(offer, "param", name=prop["name"]).text = prop["value"]

    xml_data = ET.tostring(root, encoding="utf-8", method="xml")
    return xml_data


# === Endpoint for Rozetka ===
@app.route("/export/rozetka.xml")
def rozetka_feed():
    try:
        logger.info("🖨️ Start XML feed generation")
        xml = generate_rozetka_feed()
        return Response(xml, mimetype="application/xml")
    except Exception as e:
        logger.exception("❌ Error generating feed")
        return Response("Internal Server Error", status=500)


@app.route("/")
def index():
    return "Feed Generator is Running"
