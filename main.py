from flask import Flask, Response
import os
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import logging
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_URL = os.getenv('KEYCRM_API_URL', 'https://openapi.keycrm.app/v1')
API_KEY = os.getenv('KEYCRM_API_KEY')
if not API_KEY:
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
                logger.warning(f"Rate limited. Waiting {delay} sec...")
                time.sleep(delay)
                continue
            elif response.status_code == 401:
                logger.error("401 Unauthorized – check API key")
                break
            else:
                logger.error(f"HTTP {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"Request failed: {e}")
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
            params={
                'per_page': per_page,
                'page': page
                # ❌ no filter[is_archived]
            }
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
        if not pagination.get('next_page') or pagination.get('current_page') >= pagination.get('last_page', 1):
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
            logger.error(f"Invalid offers JSON: {e}")
            break
        data = payload.get('data', [])
        if not data:
            break
        offers.extend(data)
        pagination = payload.get('meta', {}).get('pagination', {})
        if not pagination.get('next_page') or pagination.get('current_page') >= pagination.get('last_page', 1):
            break
        page += 1
        time.sleep(0.1)
    return offers

def safe_text(text):
    return str(text).strip() if text else ""

def create_xml_element(parent, tag, text=None, **attrs):
    el = ET.SubElement(parent, tag, **attrs)
    if text:
        el.text = safe_text(text)
    return el

@app.route('/export/rozetka.xml', methods=['GET'])
def rozetka_feed():
    try:
        logger.info("🛒 Start XML feed generation")
        products = fetch_products()
        if not products:
            return Response("No products", status=404)

        root = ET.Element('yml_catalog', date=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
        shop = ET.SubElement(root, 'shop')
        create_xml_element(shop, 'name', 'Znana')
        create_xml_element(shop, 'company', 'Znana')
        create_xml_element(shop, 'url', 'https://yourshop.ua')
        ET.SubElement(shop, 'currencies')
        ET.SubElement(shop, 'categories')
        offers_el = ET.SubElement(shop, 'offers')

        total = 0

        for product in products:
            prod_attr = product.get('attributes', product)
            product_id = product.get('id')
            product_name = prod_attr.get('name', f'Product {product_id}')
            description = prod_attr.get('description') or prod_attr.get('desc', '')
            common_images = prod_attr.get('pictures', []) or prod_attr.get('images', [])

            product_price = prod_attr.get('price') or prod_attr.get('selling_price') or 0
            product_stock = prod_attr.get('stock') or prod_attr.get('quantity') or 0

            variants = fetch_offers_for_product(product_id)

            if not variants:
                # fallback to product
                offer = ET.SubElement(offers_el, 'offer', id=str(product_id), available='true' if product_stock > 0 else 'false')
                create_xml_element(offer, 'name', product_name)
                create_xml_element(offer, 'description', description)
                create_xml_element(offer, 'price', f"{float(product_price):.2f}")
                create_xml_element(offer, 'stock', str(product_stock))
                create_xml_element(offer, 'currencyId', 'UAH')
                for url in common_images:
                    create_xml_element(offer, 'picture', url)
                total += 1
                continue

            for var in variants:
                var_attr = var.get('attributes', var)
                sku = var_attr.get('sku') or var_attr.get('vendor_code') or str(var.get('id'))
                if not sku:
                    continue
                stock = var_attr.get('stock') or var_attr.get('quantity') or 0
                price = var_attr.get('price') or var_attr.get('selling_price') or product_price
                try:
                    price = float(price)
                except:
                    price = 0.0

                offer = ET.SubElement(offers_el, 'offer', id=str(sku), available='true' if stock > 0 else 'false')
                create_xml_element(offer, 'name', var_attr.get('name') or product_name)
                create_xml_element(offer, 'description', var_attr.get('description') or description)
                create_xml_element(offer, 'price', f"{price:.2f}")
                create_xml_element(offer, 'stock', str(stock))
                create_xml_element(offer, 'currencyId', var_attr.get('currency_code', 'UAH'))

                if var_attr.get('old_price'):
                    try:
                        old = float(var_attr['old_price'])
                        if old > price:
                            create_xml_element(offer, 'oldprice', f"{old:.2f}")
                    except: pass

                # pictures
                pics = var_attr.get('pictures') or var_attr.get('images') or []
                if isinstance(pics, list):
                    for url in pics:
                        create_xml_element(offer, 'picture', url)
                else:
                    for url in common_images:
                        create_xml_element(offer, 'picture', url)

                total += 1

        logger.info(f"✅ Generated XML feed with {total} offers")
        xml = ET.tostring(root, encoding='unicode')
        return Response(f'<?xml version="1.0" encoding="UTF-8"?>\n{xml}', mimetype='application/xml; charset=utf-8')
    except Exception as e:
        logger.error(f"❌ XML feed error: {e}", exc_info=True)
        return Response("Internal Server Error", status=500)

@app.route('/health', methods=['GET'])
def health():
    return Response("OK", status=200)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
