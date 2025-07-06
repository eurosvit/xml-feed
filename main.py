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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load configuration from environment
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
                logger.warning(f"Rate limit hit, waiting {delay * (attempt + 1)} seconds...")
                time.sleep(delay * (attempt + 1))
            else:
                logger.error(f"HTTP {response.status_code}: {response.text}")
                response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed (attempt {attempt + 1}): {e}")
            if attempt == max_retries - 1:
                raise
            time.sleep(delay)
    return None

def fetch_products():
    products = []
    page = 1
    per_page = 50
    while True:
        logger.info(f"Fetching products page {page}")
        response = safe_request(f"{API_URL}/products", headers=HEADERS, params={'per_page': per_page, 'page': page})
        if not response:
            break
        payload = response.json()
        items = payload.get('data', [])
        if not items:
            break
        products.extend(items)
        pagination = payload.get('meta', {}).get('pagination', {})
        current_page = pagination.get('current_page')
        last_page = pagination.get('last_page', 1)
        logger.info(f"Page {current_page} of {last_page}")
        if current_page is None or last_page is None or current_page >= last_page:
            break
        page += 1
        time.sleep(0.1)
    logger.info(f"Total products fetched: {len(products)}")
    return products

def fetch_offers_for_product(product_id):
    offers = []
    page = 1
    per_page = 50
    while True:
        response = safe_request(f"{API_URL}/offers", headers=HEADERS, params={
            'filter[product_id]': product_id,
            'per_page': per_page,
            'page': page
        })
        if not response:
            break
        payload = response.json()
        items = payload.get('data', [])
        if not items:
            break
        offers.extend(items)
        pagination = payload.get('meta', {}).get('pagination', {})
        current_page = pagination.get('current_page')
        last_page = pagination.get('last_page', 1)
        if current_page is None or last_page is None or current_page >= last_page:
            break
        page += 1
        time.sleep(0.1)
    return offers

def create_xml_element(parent, tag, text=None):
    element = ET.SubElement(parent, tag)
    if text is not None:
        element.text = str(text).strip()
    return element

@app.route('/export/rozetka.xml', methods=['GET'])
def rozetka_feed():
    try:
        logger.info("\U0001F5A8️ Start XML feed generation")
        products = fetch_products()
        if not products:
            return Response("No products found", status=404)

        root = ET.Element('yml_catalog')
        root.set('date', datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))

        shop = ET.SubElement(root, 'shop')
        create_xml_element(shop, 'name', os.getenv('SHOP_NAME', 'Znana'))
        create_xml_element(shop, 'company', os.getenv('COMPANY_NAME', 'Znana'))
        create_xml_element(shop, 'url', os.getenv('SHOP_URL', 'https://yourshop.ua'))
        ET.SubElement(shop, 'currencies')
        ET.SubElement(shop, 'categories')
        offers_elem = ET.SubElement(shop, 'offers')

        for product in products:
            product_id = product.get('id')
            product_name = product.get('attributes', {}).get('name', f"Product {product_id}")
            variants = fetch_offers_for_product(product_id)
            for var in variants:
                sku = var.get('attributes', {}).get('sku')
                if not sku:
                    continue
                offer = ET.SubElement(offers_elem, 'offer', id=str(sku), available="true")
                create_xml_element(offer, 'name', product_name)
                create_xml_element(offer, 'price', var.get('attributes', {}).get('price', 0))
                create_xml_element(offer, 'currencyId', 'UAH')
                pictures = var.get('attributes', {}).get('pictures', [])
                for pic_url in pictures:
                    if pic_url:
                        create_xml_element(offer, 'picture', pic_url)

        xml_str = ET.tostring(root, encoding='unicode')
        return Response(f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_str}', mimetype='application/xml')

    except Exception as e:
        logger.error(f"\u274c Error generating feed: {e}", exc_info=True)
        return Response(f"Internal Server Error: {str(e)}", status=500)

@app.route('/health', methods=['GET'])
def health_check():
    return Response("OK", status=200)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
