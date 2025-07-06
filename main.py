from flask import Flask, Response
import os
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import logging
import time

app = Flask(__name__)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Env config
API_URL = os.getenv('KEYCRM_API_URL', 'https://openapi.keycrm.app/v1')
API_KEY = os.getenv('KEYCRM_API_KEY')

HEADERS = {'Authorization': f'Bearer {API_KEY}'}

def fetch_all_offers():
    offers = []
    page = 1
    per_page = 50
    while True:
        logger.info(f"Fetching offers page {page}")
        res = requests.get(f"{API_URL}/offers", headers=HEADERS, params={'page': page, 'limit': per_page})
        if res.status_code != 200:
            logger.warning(f"Error fetching offers: {res.status_code}")
            break
        data = res.json()
        page_offers = data.get('data', [])
        if not page_offers:
            break
        offers.extend(page_offers)
        if len(page_offers) < per_page:
            break
        page += 1
        time.sleep(0.1)
    logger.info(f"Total offers fetched: {len(offers)}")
    return offers

def fetch_offer_stock():
    logger.info("Fetching offer stocks")
    stocks = {}
    page = 1
    per_page = 50
    while True:
        res = requests.get(f"{API_URL}/offers/stocks", headers=HEADERS, params={'page': page, 'limit': per_page})
        if res.status_code != 200:
            logger.warning(f"Error fetching offer stocks: {res.status_code}")
            break
        data = res.json()
        page_data = data.get('data', [])
        if not page_data:
            break
        for entry in page_data:
            offer_id = entry.get('offer_id')
            quantity = entry.get('quantity', 0)
            if offer_id is not None:
                stocks[offer_id] = quantity
        if len(page_data) < per_page:
            break
        page += 1
        time.sleep(0.1)
    logger.info(f"Total stock entries fetched: {len(stocks)}")
    return stocks

def fetch_product_by_id(product_id):
    try:
        res = requests.get(f"{API_URL}/products/{product_id}", headers=HEADERS)
        if res.status_code == 200:
            return res.json().get('data', {})
    except Exception as e:
        logger.warning(f"Error fetching product {product_id}: {e}")
    return {}

def generate_xml():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    root = ET.Element("yml_catalog", date=now)
    shop = ET.SubElement(root, "shop")
    ET.SubElement(shop, "name").text = "Znana"
    ET.SubElement(shop, "company").text = "Znana"
    ET.SubElement(shop, "url").text = "https://yourshop.ua"

    currencies = ET.SubElement(shop, "currencies")
    ET.SubElement(currencies, "currency", id="UAH", rate="1")

    categories = ET.SubElement(shop, "categories")
    category_names = [
        "Комплекти", "Легінси", "Лонгсліви", "Майки та футболки",
        "Нижня білизна", "Нічні сорочки", "Піжами",
        "Сукні", "Халати", "Штани"
    ]
    for i, name in enumerate(category_names, start=1):
        ET.SubElement(categories, "category", id=str(i)).text = name

    offers_el = ET.SubElement(shop, "offers")
    offers = fetch_all_offers()
    stocks = fetch_offer_stock()
    logger.info(f"Rendering {len(offers)} offers")

    product_cache = {}

    for offer in offers:
        offer_id = offer['id']
        product_id = offer.get("product_id")
        if not product_id:
            continue

        if product_id in product_cache:
            product = product_cache[product_id]
        else:
            product = fetch_product_by_id(product_id)
            product_cache[product_id] = product

        product_attr = product.get("attributes", {})
        product_name = product.get("name") or offer.get("name") or ""
        product_description = product.get("description") or product_attr.get("description") or ""

        quantity = stocks.get(offer_id, offer.get("quantity", 0))

        offer_el = ET.SubElement(offers_el, "offer", id=str(offer_id), available="true" if quantity > 0 else "false")
        ET.SubElement(offer_el, "name").text = product_name
        ET.SubElement(offer_el, "price").text = str(offer.get("price", 0))
        ET.SubElement(offer_el, "currencyId").text = product_attr.get("currency_code", "UAH")
        ET.SubElement(offer_el, "categoryId").text = str(product_attr.get("category_id", 1))
        ET.SubElement(offer_el, "stock").text = str(quantity)
        if offer.get("thumbnail_url"):
            ET.SubElement(offer_el, "picture").text = offer.get("thumbnail_url")
        ET.SubElement(offer_el, "description").text = product_description

        sku = offer.get("sku") or offer.get("article") or offer.get("vendor_code") or offer.get("code")
        if sku:
            ET.SubElement(offer_el, "vendorCode").text = str(sku)

        for prop in offer.get("properties", []):
            ET.SubElement(offer_el, "param", name=prop.get("name")).text = prop.get("value")

    return ET.tostring(root, encoding="utf-8")

@app.route("/export/rozetka.xml")
def rozetka_feed():
    try:
        xml_data = generate_xml()
        return Response(xml_data, mimetype="application/xml")
    except Exception as e:
        logger.exception("Feed generation failed")
        return Response("Error generating feed", status=500)

if __name__ == "__main__":
    app.run(debug=True)
