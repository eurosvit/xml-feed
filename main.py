from flask import Flask, Response
import os
from dotenv import load_dotenv
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import logging
import time

# Load environment
load_dotenv()
app = Flask(__name__)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
API_URL = os.getenv('KEYCRM_API_URL', 'https://openapi.keycrm.app/v1')
API_KEY = os.getenv('KEYCRM_API_KEY')
if not API_KEY:
    logger.error('KEYCRM_API_KEY is not set')
    raise RuntimeError('Environment variable KEYCRM_API_KEY is required')
HEADERS = {'Authorization': f'Bearer {API_KEY}', 'Accept': 'application/json'}


def safe_request(url, headers, params=None, max_retries=3, delay=1):
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code == 200:
                return resp
            if resp.status_code == 429:
                time.sleep(delay * (attempt+1)); continue
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"Request error {e}")
            time.sleep(delay)
    return None


def fetch_products():
    products = []
    page = 1
    while True:
        logger.info(f"Fetching products page {page}")
        resp = safe_request(f"{API_URL}/products", HEADERS, params={'page': page, 'per_page': 100})
        if not resp: break
        data = resp.json().get('data', [])
        if not data: break
        products.extend(data)
        # pagination
        meta = resp.json().get('meta', {}).get('pagination', {})
        if not meta.get('next_page'): break
        page += 1
    logger.info(f"Total products fetched: {len(products)}")
    return products


def fetch_offers_for_product(product_id):
    offers = []
    page = 1
    while True:
        resp = safe_request(f"{API_URL}/offers", HEADERS,
                            params={'filter[product_id]': product_id, 'page': page, 'per_page': 100})
        if not resp: break
        data = resp.json().get('data', [])
        if not data: break
        offers.extend(data)
        meta = resp.json().get('meta', {}).get('pagination', {})
        if not meta.get('next_page'): break
        page += 1
    logger.info(f"Fetched {len(offers)} offers for {product_id}")
    return offers


def create_xml_element(parent, tag, text=None, **attrs):
    el = ET.SubElement(parent, tag, **attrs)
    if text is not None:
        el.text = str(text)
    return el


@app.route('/export/rozetka.xml')
def rozetka_feed():
    products = fetch_products()
    root = ET.Element('yml_catalog', date=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
    shop = ET.SubElement(root, 'shop')
    create_xml_element(shop, 'name', os.getenv('SHOP_NAME', 'Znana'))
    create_xml_element(shop, 'company', os.getenv('COMPANY_NAME', 'Znana'))
    create_xml_element(shop, 'url', os.getenv('SHOP_URL', 'https://yourshop.ua'))
    cur = ET.SubElement(shop, 'currencies')
    ET.SubElement(cur, 'currency', id='UAH', rate='1')
    ET.SubElement(shop, 'categories')
    offers_el = ET.SubElement(shop, 'offers')

    for p in products:
        # choose variants or single
        if p.get('has_offers'):
            items = fetch_offers_for_product(p['id'])
        else:
            items = [p]

        for item in items:
            sku = item.get('sku')
            if not sku: continue
            qty = item.get('quantity', item.get('stock', 0))
            price = item.get('price', 0)
            desc = item.get('description')
            # pictures
            pics = item.get('attachments_data') or []
            thumb = item.get('thumbnail_url')
            if thumb: pics.insert(0, thumb)
            # build offer
            off = ET.SubElement(offers_el, 'offer', id=sku, available=('true' if qty>0 else 'false'))
            create_xml_element(off, 'sku', sku)
            create_xml_element(off, 'vendor', os.getenv('COMPANY_NAME', 'Znana'))
                        # color & size from custom_fields
            color = None
            size = None
            for cf in item.get('custom_fields', []):
                name_field = cf.get('name', '').lower()
                if 'колір' in name_field or 'color' in name_field:
                    color = cf.get('value')
                if 'розмір' in name_field or 'size' in name_field:
                    size = cf.get('value')
            if color:
                create_xml_element(off, 'color', color)
            if size:
                create_xml_element(off, 'size', size)
