from flask import Flask, Response
import os
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import logging

app = Flask(__name__)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Env config
API_URL = os.getenv('KEYCRM_API_URL', 'https://openapi.keycrm.app/v1')
API_KEY = os.getenv('KEYCRM_API_KEY')

HEADERS = {'Authorization': f'Bearer {API_KEY}'}

def fetch_offers():
    offers = []
    page = 1
    per_page = 100  # запитуємо більше оферів
    while True:
        logger.info(f"Fetching offers page {page}")
        res = requests.get(f"{API_URL}/offers", headers=HEADERS, params={'page': page, 'per_page': per_page})
        if res.status_code != 200:
            logger.warning(f"Error fetching offers: {res.status_code}")
            break
        data = res.json()
        page_offers = data.get('data', [])
        if not page_offers:
            break
        offers.extend(page_offers)
        pagination = data.get('meta', {}).get('pagination', {})
        if not pagination or pagination.get('current_page') >= pagination.get('last_page', page):
            break
        page += 1
    return offers

def generate_xml():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    root = ET.Element("yml_catalog", date=now)
    shop = ET.SubElement(root, "shop")
    ET.SubElement(shop, "name").text = "Znana"
    ET.SubElement(shop, "company").text = "Znana"
    ET.SubElement(shop, "url").text = "https://yourshop.ua"

    # Currency
    currencies = ET.SubElement(shop, "currencies")
    ET.SubElement(currencies, "currency", id="UAH", rate="1")

    # Categories (hardcoded example)
    categories = ET.SubElement(shop, "categories")
    category_names = [
        "Комплекти", "Легінси", "Лонгсліви", "Майки та футболки",
        "Нижня білизна", "Нічні сорочки", "Піжами",
        "Сукні", "Халати", "Штани"
    ]
    for i, name in enumerate(category_names, start=1):
        ET.SubElement(categories, "category", id=str(i)).text = name

    # Offers
    offers_el = ET.SubElement(shop, "offers")
    offers = fetch_offers()
    logger.info(f"Rendering {len(offers)} offers")

    for offer in offers:
        if not offer.get("product"):
            continue
        product = offer["product"]

        offer_el = ET.SubElement(offers_el, "offer", id=str(offer['id']))
        ET.SubElement(offer_el, "name").text = product.get("name") or ""
        ET.SubElement(offer_el, "price").text = str(offer.get("price", 0))
        ET.SubElement(offer_el, "currencyId").text = product.get("currency_code", "UAH")
        ET.SubElement(offer_el, "categoryId").text = str(product.get("category_id", 1))
        ET.SubElement(offer_el, "quantity").text = str(offer.get("quantity", 0))
        if offer.get("thumbnail_url"):
            ET.SubElement(offer_el, "picture").text = offer.get("thumbnail_url")
        ET.SubElement(offer_el, "description").text = product.get("description") or ""

        # Params
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
