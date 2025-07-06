from flask import Flask, Response
import os, requests, xml.etree.ElementTree as ET, logging, time
from datetime import datetime
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
    # (як у тебе був — без змін)
    ...

def fetch_products():
    # (як і раніше — цілком)
    ...

def fetch_offers_for_product(product_id):
    # (як і раніше — цілком)
    ...

def get_all_images(product_attr, variant_attr=None):
    # (як і раніше — цілком)
    ...

def safe_text(text):
    # (як і раніше)
    ...

def create_xml_element(parent, tag, text=None, **attrs):
    # (як і раніше)
    ...

def generate_feed_xml():
    logger.info("Запуск збірки XML-фіду")
    products = fetch_products()
    root = ET.Element('yml_catalog', date=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
    shop = ET.SubElement(root, 'shop')
    create_xml_element(shop, 'name', os.getenv('SHOP_NAME', 'Znana'))
    create_xml_element(shop, 'company', os.getenv('COMPANY_NAME', 'Znana'))
    create_xml_element(shop, 'url', os.getenv('SHOP_URL', 'https://yourshop.ua'))

    currencies = ET.SubElement(shop, 'currencies')
    ET.SubElement(currencies, 'currency', id='UAH', rate='1')

    ET.SubElement(shop, 'categories')
    offers_elem = ET.SubElement(shop, 'offers')

    total_offers = 0
    for product in products:
        prod_attr = product.get('attributes', product.get('data', {}).get('attributes', product))
        product_id = product.get('id') or product.get('data', {}).get('id')
        variants = fetch_offers_for_product(product_id)
        for var in variants:
            var_attr = var.get('attributes', var.get('data', {}).get('attributes', var))
            sku = var_attr.get('sku') or var_attr.get('article') or var_attr.get('vendor_code') or str(var.get('id'))
            if not sku:
                logger.warning(f"Пропуск варианта без SKU: product {product_id}")
                continue

            try:
                stock = int(float(var_attr.get('stock') or var_attr.get('quantity') or 0))
            except:
                stock = 0
            available = 'true' if stock > 0 else 'false'

            offer = ET.SubElement(offers_elem, 'offer', id=str(sku), available=available)

            price = float(var_attr.get('price') or var_attr.get('selling_price') or 0)
            create_xml_element(offer, 'price', f"{price:.2f}")

            old = var_attr.get('discount_price') or var_attr.get('old_price')
            if old:
                try:
                    old = float(old)
                    if old > price:
                        create_xml_element(offer, 'oldprice', f"{old:.2f}")
                except: pass

            create_xml_element(offer, 'stock', str(stock))
            create_xml_element(offer, 'currencyId', var_attr.get('currency_code', 'UAH'))

            name = var_attr.get('name') or prod_attr.get('name', '')
            create_xml_element(offer, 'name', name)

            desc = var_attr.get('description') or prod_attr.get('description', '')
            if desc:
                create_xml_element(offer, 'description', desc)

            barcode = var_attr.get('barcode') or var_attr.get('ean')
            if barcode:
                create_xml_element(offer, 'barcode', barcode)

            cat_id = var_attr.get('category_id') or prod_attr.get('category_id')
            if cat_id:
                create_xml_element(offer, 'categoryId', str(cat_id))

            all_images = get_all_images(prod_attr, var_attr)
            for url in all_images:
                create_xml_element(offer, 'picture', url)

            # color, size
            custom = var_attr.get('custom_fields', [])
            for cf in custom:
                uuid = cf.get('uuid','').lower()
                val = cf.get('value')
                if not val: continue
                if 'color' in uuid or 'колір' in uuid:
                    create_xml_element(offer, 'color', val)
                if 'size' in uuid or 'розмір' in uuid:
                    create_xml_element(offer, 'size', val)
                param = ET.SubElement(offer, 'param', name=uuid)
                param.text = safe_text(val)

            total_offers += 1

    logger.info(f"Згенеровано оферів: {total_offers}")
    xml = ET.tostring(root, encoding='unicode')
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml
    return xml

@app.route('/feed.xml', methods=['GET'])
def feed():
    xml = generate_feed_xml()
    return Response(xml, mimetype='application/xml; charset=utf-8')

@app.route('/health', methods=['GET'])
def health():
    return Response("OK", status=200)

if __name__=='__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT',8080)))
