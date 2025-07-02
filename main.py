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

# Load configuration from environment
API_URL = os.getenv('KEYCRM_API_URL', 'https://openapi.keycrm.app/v1')
API_KEY = os.getenv('KEYCRM_API_KEY')
if not API_KEY:
    app.logger.error('KEYCRM_API_KEY is not set')
    raise RuntimeError('Environment variable KEYCRM_API_KEY is required')

# Prepare headers for Key CRM API
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
        app.logger.info(f'Fetching products page {page}')
        resp = requests.get(
            f"{API_URL}/products",
            headers=HEADERS,
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
    app.logger.info(f'Total products fetched: {len(products)}')
    return products

# Fetch all categories if supported
def fetch_categories():
    categories = []
    page = 1
    per_page = 100
    while True:
        resp = requests.get(
            f"{API_URL}/categories",
            headers=HEADERS,
            params={'per_page': per_page, 'page': page}
        )
        if resp.status_code == 404:
            app.logger.warning('Categories endpoint not found, skipping categories section')
            return []
        if resp.status_code != 200:
            app.logger.error(f"Key CRM /categories error {resp.status_code}: {resp.text}")
            # skip categories on any error
            return []
        data = resp.json()
        items = data.get('data', [])
        if not items:
            break
        categories.extend(items)
        pagination = data.get('meta', {}).get('pagination', {})
        if not pagination.get('next_page'):
            break
        page += 1
    return categories

@app.route('/export/rozetka.xml', methods=['GET'])
def rozetka_feed():
    try:
        # Fetch data
        products = fetch_products()
        categories_list = fetch_categories()

        # Build YML catalog
        root = ET.Element('yml_catalog', date=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
        shop = ET.SubElement(root, 'shop')
        ET.SubElement(shop, 'name').text = os.getenv('SHOP_NAME', 'Znana')
        ET.SubElement(shop, 'company').text = os.getenv('COMPANY_NAME', 'Znana')
        ET.SubElement(shop, 'url').text = os.getenv('SHOP_URL', 'Znana Maternity')

        # Currencies
        currencies = ET.SubElement(shop, 'currencies')
        ET.SubElement(currencies, 'currency', id='UAH', rate='1')

        # Categories (optional)
        if categories_list:
            cats_elem = ET.SubElement(shop, 'categories')
            for c in categories_list:
                cid = c.get('id')
                name = c.get('name') or c.get('title')
                parent = c.get('parent_id')
                attrs = {'id': str(cid)}
                if parent:
                    attrs['parentId'] = str(parent)
                ET.SubElement(cats_elem, 'category', **attrs).text = name

        # Offers section
        offers = ET.SubElement(shop, 'offers')
        for p in products:
            sku = p.get('sku')
            if not sku:
                continue
            available = 'true' if p.get('stock', 0) > 0 else 'false'
            offer = ET.SubElement(offers, 'offer', id=sku, available=available)

            # Price and stock
            ET.SubElement(offer, 'price').text = f"{p.get('price', 0):.2f}"
            ET.SubElement(offer, 'stock').text = str(p.get('stock', 0))

            # Name and description
            if p.get('name'):
                ET.SubElement(offer, 'name').text = p['name']
            if p.get('description'):
                ET.SubElement(offer, 'description').text = p['description']

            # Barcode
            if p.get('barcode'):
                ET.SubElement(offer, 'barcode').text = p['barcode']

            # Currency and purchase price
            if p.get('currency_code'):
                ET.SubElement(offer, 'currencyId').text = p['currency_code']
            if p.get('purchased_price') is not None:
                ET.SubElement(offer, 'purchase_price').text = f"{p['purchased_price']:.2f}"

            # Unit, dimensions and weight
            if p.get('unit_type'):
                ET.SubElement(offer, 'unit').text = p['unit_type']
            for dim in ('weight', 'length', 'width', 'height'):
                if p.get(dim) is not None:
                    ET.SubElement(offer, dim).text = str(p[dim])

            # Category reference
            if p.get('category_id'):
                ET.SubElement(offer, 'categoryId').text = str(p['category_id'])

            # Custom fields
            for cf in p.get('custom_fields', []):
                if cf.get('uuid') and cf.get('value'):
                    ET.SubElement(offer, 'param', name=cf['uuid']).text = cf['value']

            # Pictures
            for pic_url in p.get('pictures', []):
                ET.SubElement(offer, 'picture').text = pic_url

        # Convert to bytes and return
        xml_bytes = ET.tostring(root, encoding='utf-8', xml_declaration=True)
        return Response(xml_bytes, mimetype='application/xml')

    except Exception as e:
        app.logger.error(f"Error generating feed: {e}")
        return Response("Internal Server Error", status=500)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
