from flask import Flask, Response
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import logging
import time

app = Flask(__name__)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Config
API_URL = os.getenv('KEYCRM_API_URL', 'https://openapi.keycrm.app/v1')
API_KEY = os.getenv('KEYCRM_API_KEY')
if not API_KEY:
    logger.error('KEYCRM_API_KEY is not set')
    raise RuntimeError('Environment variable KEYCRM_API_KEY is required')

HEADERS = {
    'Authorization': f'Bearer {API_KEY}',
    'Accept': 'application/json',
    'Content-Type': 'application/json'
}

def safe_request(url, headers, params=None, max_retries=3, delay=1):
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            if response.status_code == 200:
                return response
            elif response.status_code == 429:
                logger.warning(f"Rate limited. Waiting {delay * (attempt + 1)}s...")
                time.sleep(delay * (attempt + 1))
                continue
            elif response.status_code == 401:
                logger.error("401 Unauthorized – check API key")
                raise requests.exceptions.HTTPError("401 Unauthorized")
            else:
                logger.error(f"HTTP {response.status_code}: {response.text}")
                response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            if attempt == max_retries - 1:
                raise
            time.sleep(delay)
    return None

def fetch_products():
    products = []
    page = 1
    per_page = 50

    while True:
        logger.info(f"📦 Fetching products page {page}")
        resp = safe_request(
            f"{API_URL}/products",
            headers=HEADERS,
            params={'per_page': per_page, 'page': page}
        )
        if not resp:
            break

        try:
            payload = resp.json()
        except Exception as e:
            logger.error(f"❌ Invalid JSON: {e}")
            break

        data = payload.get('data', [])
        if not data:
            break

        products.extend(data)

        pagination = payload.get('meta', {}).get('pagination', {})
        current_page = pagination.get('current_page')
        last_page = pagination.get('last_page')

        logger.info(f"📄 Page {current_page} of {last_page}")

        if current_page is None or last_page is None or current_page >= last_page:
            break

        page += 1
        time.sleep(0.2)

    logger.info(f"✅ Total products fetched: {len(products)}")
    return products

def fetch_offers_for_product(product_id):
    offers = []
    page = 1
    per_page = 50

    while True:
        resp = safe_request(
            f"{API_URL}/offers",
            headers=HEADERS,
            params={
                'filter[product_id]': product_id,
                'per_page': per_page,
                'page': page
            }
        )
        if not resp:
            break

        try:
            payload = resp.json()
        except Exception as e:
            logger.error(f"❌ Invalid JSON (offers): {e}")
            break

        data = payload.get('data', [])
        if not data:
            break

        offers.extend(data)

        pagination = payload.get('meta', {}).get('pagination', {})
        if pagination.get('current_page') >= pagination.get('last_page', 1):
            break

        page += 1
        time.sleep(0.1)

    return offers

def safe_text(text):
    return str(text).strip() if text else ""

def create_xml_element(parent, tag, text=None, **attrs):
    element = ET.SubElement(parent, tag, **attrs)
    if text is not None:
        element.text = safe_text(text)
    return element

@app.route('/export/rozetka.xml', methods=['GET'])
def rozetka_feed():
    try:
        logger.info("🖨️ Start XML feed generation")

        products = fetch_products()
        if not products:
            return Response("No products", status=404)

        root = ET.Element('yml_catalog')
        root.set('date', datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
        shop = ET.SubElement(root, 'shop')
        create_xml_element(shop, 'name', os.getenv('SHOP_NAME', 'Znana'))
        create_xml_element(shop, 'company', os.getenv('COMPANY_NAME', 'Znana'))
        create_xml_element(shop, 'url', os.getenv('SHOP_URL', 'https://yourshop.ua'))
        ET.SubElement(shop, 'currencies')
        ET.SubElement(shop, 'categories')
        offers_elem = ET.SubElement(shop, 'offers')

        offer_count = 0
        for product in products:
            prod_attr = product.get('attributes', product)
            product_id = product.get('id')

            variants = fetch_offers_for_product(product_id)
            if not variants:
                offer = ET.SubElement(offers_elem, 'offer')
                offer.set('id', str(product_id))
                offer.set('available', 'true')

                create_xml_element(offer, 'name', prod_attr.get('name'))
                create_xml_element(offer, 'price', str(prod_attr.get('price', '0')))
                create_xml_element(offer, 'currencyId', 'UAH')

                for pic in prod_attr.get('pictures', []):
                    create_xml_element(offer, 'picture', pic)

                offer_count += 1
                continue

            for var in variants:
                var_attr = var.get('attributes', var)
                variant_id = var.get('id')
                sku = var_attr.get('sku') or var_attr.get('article') or var_attr.get('code') or f"v{variant_id}"
                stock = int(var_attr.get('stock', 0) or 0)
                price = float(var_attr.get('price') or 0)

                offer = ET.SubElement(offers_elem, 'offer')
                offer.set('id', str(sku))
                offer.set('available', 'true' if stock > 0 else 'false')

                create_xml_element(offer, 'name', var_attr.get('name') or prod_attr.get('name'))
                create_xml_element(offer, 'price', f"{price:.2f}")
                create_xml_element(offer, 'stock', str(stock))
                create_xml_element(offer, 'currencyId', 'UAH')

                for pic in var_attr.get('pictures', []) or prod_attr.get('pictures', []):
                    create_xml_element(offer, 'picture', pic)

                offer_count += 1

        logger.info(f"✅ Generated XML feed with {offer_count} offers")
        xml_str = ET.tostring(root, encoding='unicode')
        xml_response = f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_str}'
        return Response(xml_response, mimetype='application/xml')

    except Exception as e:
        logger.error(f"❌ Error generating feed: {e}", exc_info=True)
        return Response("Internal Server Error", status=500)

@app.route('/health', methods=['GET'])
def health():
    return Response("OK", status=200)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
