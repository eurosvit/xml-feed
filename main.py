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

# Common headers for Key CRM API
HEADERS = {
    'Authorization': f'Bearer {API_KEY}',
    'Accept': 'application/json',
    'Content-Type': 'application/json'
}

def safe_request(url, headers, params=None, max_retries=3, delay=1):
    """Make a safe HTTP request with retry logic and error handling"""
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            if response.status_code == 200:
                return response
            elif response.status_code == 429:  # Rate limit
                logger.warning(f"Rate limit hit, waiting {delay * (attempt + 1)} seconds...")
                time.sleep(delay * (attempt + 1))
                continue
            elif response.status_code == 401:
                logger.error("Authentication failed - check API key")
                raise requests.exceptions.HTTPError("401 Unauthorized - check API key")
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
    """Fetch all products with improved pagination and error handling"""
    products = []
    page = 1
    per_page = 50
    while True:
        logger.info(f"Fetching products page {page}")
        response = safe_request(f"{API_URL}/products", HEADERS, params={'per_page': per_page, 'page': page})
        if not response:
            logger.error(f"Failed to fetch products page {page}")
            break
        try:
            payload = response.json()
        except ValueError as e:
            logger.error(f"Invalid JSON response: {e}")
            break
        items = payload.get('data', [])
        if not items:
            break
        products.extend(items)
        meta = payload.get('meta', {}).get('pagination', {})
        if not meta.get('next_page'):
            break
        page += 1
        time.sleep(0.1)
    logger.info(f"Total products fetched: {len(products)}")
    return products

def fetch_offers_for_product(product_id):
    """Fetch offers (variants) for a single product with improved error handling"""
    offers = []
    page = 1
    per_page = 50
    while True:
        response = safe_request(f"{API_URL}/offers", HEADERS, params={'filter[product_id]': product_id, 'per_page': per_page, 'page': page})
        if not response:
            break
        try:
            payload = response.json()
        except ValueError:
            break
        items = payload.get('data', [])
        if not items:
            break
        offers.extend(items)
        meta = payload.get('meta', {}).get('pagination', {})
        if not meta.get('next_page'):
            break
        page += 1
        time.sleep(0.05)
    logger.info(f"Fetched {len(offers)} offers for product {product_id}")
    return offers

def safe_text(text):
    return str(text).strip() if text is not None else ""

def create_xml_element(parent, tag, text=None, **attrs):
    element = ET.SubElement(parent, tag, **attrs)
    if text is not None:
        element.text = safe_text(text)
    return element

@app.route('/export/rozetka.xml', methods=['GET'])
def rozetka_feed():
    try:
        products = fetch_products()
        root = ET.Element('yml_catalog')
        root.set('date', datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
        shop = ET.SubElement(root, 'shop')
        create_xml_element(shop, 'name', os.getenv('SHOP_NAME', 'Znana'))
        create_xml_element(shop, 'company', os.getenv('COMPANY_NAME', 'Znana'))
        create_xml_element(shop, 'url', os.getenv('SHOP_URL', 'https://yourshop.ua'))
        currencies = ET.SubElement(shop, 'currencies')
        ET.SubElement(currencies, 'currency', id='UAH', rate='1')
        create_xml_element(shop, 'categories')
        offers_elem = ET.SubElement(shop, 'offers')
        offer_count = 0
        for product in products:
            if 'attributes' in product:
                prod_attr = product['attributes']
                product_id = product.get('id')
            else:
                prod_attr = product
                product_id = product.get('id')
            common_desc = prod_attr.get('description', '')
            common_pics = prod_attr.get('pictures', [])
            product_name = prod_attr.get('name', '')
            product_price = prod_attr.get('price', 0)
            product_stock = prod_attr.get('stock', 0)
            variants = fetch_offers_for_product(product_id)
            if not variants:
                variants = [{'attributes': prod_attr, 'id': product_id}]
            for var in variants:
                attr = var.get('attributes', var)
                sku = attr.get('sku') or ''
                if not sku:
                    continue
                stock = int(attr.get('stock', product_stock) or 0)
                price = float(attr.get('price', product_price) or 0)
                offer = ET.SubElement(offers_elem, 'offer', id=str(sku), available='true' if stock>0 else 'false')
                # SKU and vendor
                create_xml_element(offer, 'sku', sku)
                create_xml_element(offer, 'vendor', os.getenv('COMPANY_NAME', 'Znana'))
                # Color and size
                color = attr.get('color')
                if not color:
                    for cf in attr.get('custom_fields', []):
                        if cf.get('uuid','').lower()=='color':
                            color = cf.get('value')
                            break
                if color:
                    create_xml_element(offer, 'color', color)
                size = attr.get('size')
                if not size:
                    for cf in attr.get('custom_fields', []):
                        if cf.get('uuid','').lower()=='size':
                            size = cf.get('value')
                            break
                if size:
                    create_xml_element(offer, 'size', size)
                # Price and stock
                create_xml_element(offer, 'price', f"{price:.2f}")
                create_xml_element(offer, 'stock', str(stock))
                # Name and description
                create_xml_element(offer, 'name', attr.get('name') or product_name)
                desc = attr.get('description') or common_desc
                if desc:
                    create_xml_element(offer, 'description', desc)
                # Barcode
                if attr.get('barcode'):
                    create_xml_element(offer, 'barcode', attr['barcode'])
                create_xml_element(offer, 'currencyId', attr.get('currency_code','UAH'))
                # Pictures
                pics = attr.get('pictures',[]) or common_pics
                for url in pics:
                    if url:
                        create_xml_element(offer, 'picture', url)
                offer_count += 1
        xml_str = ET.tostring(root, encoding='unicode')
        xml_header = '<?xml version="1.0" encoding="UTF-8"?>\n'
        return Response(xml_header+xml_str, mimetype='application/xml; charset=utf-8')
    except Exception as e:
        logger.error(f"Error generating feed: {e}", exc_info=True)
        return Response("Internal Server Error", status=500)

@app.route('/health', methods=['GET'])
def health():
    return Response('OK', status=200)

if __name__ == '__main__':
    port = int(os.getenv('PORT',8080))
    app.run(host='0.0.0.0', port=port)
