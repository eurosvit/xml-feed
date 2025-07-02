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

app = Flask(__name__)

# Environment variables
API_URL = os.getenv('KEYCRM_API_URL', 'https://openapi.keycrm.app/v1')
API_KEY = os.getenv('KEYCRM_API_KEY')
if not API_KEY:
    app.logger.error("KEYCRM_API_KEY is not set")
    raise RuntimeError("Environment variable KEYCRM_API_KEY is required")

HEADERS = {
    'Authorization': f'Bearer {API_KEY}',
    'Accept': 'application/json'
}

# Fetch all products with pagination
def fetch_products():
    products = []
    page = 1
    per_page = 100
    while True:
        resp = requests.get(
            f"{API_URL}/products", headers=HEADERS,
            params={'per_page': per_page, 'page': page}
        )
        if resp.status_code != 200:
            app.logger.error(f"Key CRM /products error {resp.status_code}: {resp.text}")
            resp.raise_for_status()
        data = resp.json()
        items = data.get('data', [])
        if not items:
            break
        products.extend(items)
        pagination = data.get('meta', {}).get('pagination', {})
        if not pagination.get('next_page'):
            break
        page += 1
    return products

# Fetch variants for a single product, return empty list on 404
def fetch_variants(product_id):
    resp = requests.get(f"{API_URL}/products/{product_id}/variants", headers=HEADERS)
    if resp.status_code == 404:
        app.logger.warning(f"No variants for product {product_id}: 404")
        return []
    if resp.status_code != 200:
        app.logger.error(f"Key CRM /products/{product_id}/variants error {resp.status_code}: {resp.text}")
        resp.raise_for_status()
    return resp.json().get('data', [])

# Fetch images for a single product, return empty list on 404
def fetch_images(product_id):
    resp = requests.get(f"{API_URL}/products/{product_id}/images", headers=HEADERS)
    if resp.status_code == 404:
        app.logger.warning(f"No images for product {product_id}: 404")
        return []
    if resp.status_code != 200:
        app.logger.warning(f"Key CRM /products/{product_id}/images error {resp.status_code}")
        return []
    return resp.json().get('data', [])

@app.route('/export/rozetka.xml', methods=['GET'])
def rozetka_feed():
    try:
        products = fetch_products()

        # Build XML
        root = ET.Element('yml_catalog', date=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
        shop = ET.SubElement(root, 'shop')
        ET.SubElement(shop, 'name').text = os.getenv('SHOP_NAME', 'Ваша Компанія')
        ET.SubElement(shop, 'company').text = os.getenv('COMPANY_NAME', 'Ваша Компанія LLC')
        ET.SubElement(shop, 'url').text = os.getenv('SHOP_URL', 'https://yourshop.ua')

        currencies = ET.SubElement(shop, 'currencies')
        ET.SubElement(currencies, 'currency', id='UAH', rate='1')

        offers = ET.SubElement(shop, 'offers')
        for p in products:
            product_name = p.get('name', '')
            product_desc = p.get('description', '')
            product_barcode = p.get('barcode')
            product_pictures = p.get('pictures', [])
            product_unit = p.get('unit_type')
            product_weight = p.get('weight')
            product_length = p.get('length')
            product_width = p.get('width')
            product_height = p.get('height')
            product_category = p.get('category_id')
            product_currency = p.get('currency_code')
            product_purchase_price = p.get('purchased_price')
            custom_fields = p.get('custom_fields', [])

            images = [img for img in product_pictures]
            # override if separate images endpoint
            fetched_imgs = fetch_images(p['id'])
            if fetched_imgs:
                images = [img.get('url') or img.get('src') for img in fetched_imgs if img.get('url') or img.get('src')]

            for v in fetch_variants(p['id']):
                sku = v.get('sku')
                if not sku:
                    continue
                available = 'true' if v.get('stock', 0) > 0 else 'false'
                offer = ET.SubElement(offers, 'offer', id=sku, available=available)

                # Name, price, stock
                if product_name:
                    ET.SubElement(offer, 'name').text = product_name
                price = v.get('price', p.get('price', 0))
                ET.SubElement(offer, 'price').text = f"{price:.2f}"
                if product_purchase_price:
                    ET.SubElement(offer, 'purchase_price').text = f"{product_purchase_price:.2f}"
                if product_currency:
                    ET.SubElement(offer, 'currencyId').text = product_currency
                ET.SubElement(offer, 'stock').text = str(v.get('stock', 0))

                # Barcode
                barcode = v.get('barcode', product_barcode)
                if barcode:
                    ET.SubElement(offer, 'barcode').text = barcode

                # Unit, dimensions
                if product_unit:
                    ET.SubElement(offer, 'unit').text = product_unit
                if product_weight is not None:
                    ET.SubElement(offer, 'weight').text = str(product_weight)
                if product_length is not None:
                    ET.SubElement(offer, 'length').text = str(product_length)
                if product_width is not None:
                    ET.SubElement(offer, 'width').text = str(product_width)
                if product_height is not None:
                    ET.SubElement(offer, 'height').text = str(product_height)
                if product_category:
                    ET.SubElement(offer, 'categoryId').text = str(product_category)

                # Params color/size
                if v.get('color'):
                    ET.SubElement(offer, 'param', name='color').text = v['color']
                if v.get('size'):
                    ET.SubElement(offer, 'param', name='size').text = v['size']

                # Description
                desc = v.get('description') or product_desc
                if desc:
                    ET.SubElement(offer, 'description').text = desc

                # Pictures
                variant_pics = v.get('pictures', [])
                pic_urls = [img for img in variant_pics] or images
                for url in pic_urls:
                    ET.SubElement(offer, 'picture').text = url

                # Custom fields
                for cf in custom_fields:
                    uuid = cf.get('uuid')
                    val = cf.get('value')
                    if uuid and val:
                        ET.SubElement(offer, 'param', name=uuid).text = val

        xml_bytes = ET.tostring(root, encoding='utf-8', xml_declaration=True)
        return Response(xml_bytes, mimetype='application/xml')
    except Exception as e:
        app.logger.error(f"Error generating feed: {e}")
        return Response("Internal Server Error", status=500)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
