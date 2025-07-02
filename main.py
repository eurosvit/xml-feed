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
# Each product record has 'attributes' dict where price, stock, sku live
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
        items = data.get('data', [])  # list of resource objects
        if not items:
            break
        products.extend(items)
        pagination = data.get('meta', {}).get('pagination', {})
        if not pagination.get('next_page'):
            break
        page += 1
    app.logger.info(f'Total products fetched: {len(products)}')
    return products

@app.route('/export/rozetka.xml', methods=['GET'])
def rozetka_feed():
    try:
        products = fetch_products()

        # Build YML catalog
        root = ET.Element('yml_catalog', date=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
        shop = ET.SubElement(root, 'shop')
        ET.SubElement(shop, 'name').text = os.getenv('SHOP_NAME', 'Znana')
        ET.SubElement(shop, 'company').text = os.getenv('COMPANY_NAME', 'Znana')
        ET.SubElement(shop, 'url').text = os.getenv('SHOP_URL', 'Znana Maternity')

        # Currencies
        currencies = ET.SubElement(shop, 'currencies')
        ET.SubElement(currencies, 'currency', id='UAH', rate='1')

        # Offers section
        offers = ET.SubElement(shop, 'offers')
        for record in products:
            attr = record.get('attributes', {})
            sku = attr.get('sku')
            if not sku:
                continue
            available = 'true' if attr.get('stock', 0) > 0 else 'false'
            offer = ET.SubElement(offers, 'offer', id=sku, available=available)

            # Price and stock
            price = attr.get('price', 0)
            stock = attr.get('stock', 0)
            ET.SubElement(offer, 'price').text = f"{price:.2f}"
            ET.SubElement(offer, 'stock').text = str(stock)

            # Name and description
            if attr.get('name'):
                ET.SubElement(offer, 'name').text = attr['name']
            if attr.get('description'):
                ET.SubElement(offer, 'description').text = attr['description']

            # Barcode
            if attr.get('barcode'):
                ET.SubElement(offer, 'barcode').text = attr['barcode']

            # Currency and purchase price
            if attr.get('currency_code'):
                ET.SubElement(offer, 'currencyId').text = attr['currency_code']
            if attr.get('purchased_price') is not None:
                ET.SubElement(offer, 'purchase_price').text = f"{attr['purchased_price']:.2f}"

            # Unit, dimensions and weight
            if attr.get('unit_type'):
                ET.SubElement(offer, 'unit').text = attr['unit_type']
            for dim in ('weight', 'length', 'width', 'height'):
                if attr.get(dim) is not None:
                    ET.SubElement(offer, dim).text = str(attr[dim])

            # Category reference
            if attr.get('category_id'):
                ET.SubElement(offer, 'categoryId').text = str(attr['category_id'])

            # Custom fields
            for cf in attr.get('custom_fields', []):
                if cf.get('uuid') and cf.get('value'):
                    ET.SubElement(offer, 'param', name=cf['uuid']).text = cf['value']

            # Pictures (if returned inline)
            for pic_url in attr.get('pictures', []):
                ET.SubElement(offer, 'picture').text = pic_url

        xml_bytes = ET.tostring(root, encoding='utf-8', xml_declaration=True)
        return Response(xml_bytes, mimetype='application/xml')

    except Exception as e:
        app.logger.error(f"Error generating feed: {e}")
        return Response("Internal Server Error", status=500)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
