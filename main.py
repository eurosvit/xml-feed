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

# Common headers for Key CRM API
HEADERS = {
    'Authorization': f'Bearer {API_KEY}',
    'Accept': 'application/json'
}

# Fetch all products (base items with minimal attributes)
def fetch_products():
    products = []
    page = 1
    per_page = 100
    while True:
        resp = requests.get(
            f"{API_URL}/products",
            headers=HEADERS,
            params={'per_page': per_page, 'page': page}
        )
        if resp.status_code != 200:
            app.logger.error(f"Error fetching products: {resp.status_code} {resp.text}")
            resp.raise_for_status()
        payload = resp.json()
        items = payload.get('data', [])
        if not items:
            break
        products.extend(items)
        pagination = payload.get('meta', {}).get('pagination', {})
        if not pagination.get('next_page'):
            break
        page += 1
    return products

# Fetch variants (offers) of a single product using the correct endpoint
def fetch_variants(product_id):
    resp = requests.get(
        f"{API_URL}/products/{product_id}/offers",
        headers=HEADERS
    )
    if resp.status_code == 404:
        # No variants for this product
        return []
    if resp.status_code != 200:
        app.logger.error(f"Error fetching variants for {product_id}: {resp.status_code} {resp.text}")
        resp.raise_for_status()
    return resp.json().get('data', [])

@app.route('/export/rozetka.xml', methods=['GET'])
def rozetka_feed():
    try:
        products = fetch_products()

        # Build root
        root = ET.Element('yml_catalog', date=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
        shop = ET.SubElement(root, 'shop')
        ET.SubElement(shop, 'name').text = os.getenv('SHOP_NAME', 'Znana')
        ET.SubElement(shop, 'company').text = os.getenv('COMPANY_NAME', 'Znana')
        ET.SubElement(shop, 'url').text = os.getenv('SHOP_URL', 'https://yourshop.ua')

        # Currencies
        currencies = ET.SubElement(shop, 'currencies')
        ET.SubElement(currencies, 'currency', id='UAH', rate='1')

        # Offers
        offers_elem = ET.SubElement(shop, 'offers')
        for product in products:
            prod_attr = product.get('attributes', {})
            # General product fields (e.g., description, images)
            common_desc = prod_attr.get('description')
            common_pics = prod_attr.get('pictures', [])

            variants = fetch_variants(product.get('id'))
            for var in variants:
                var_attr = var.get('attributes', {})
                sku = var_attr.get('sku')
                if not sku:
                    continue
                available = 'true' if var_attr.get('stock', 0) > 0 else 'false'
                offer = ET.SubElement(offers_elem, 'offer', id=sku, available=available)

                # Price and stock
                ET.SubElement(offer, 'price').text = f"{var_attr.get('price', 0):.2f}"
                ET.SubElement(offer, 'stock').text = str(var_attr.get('stock', 0))

                # Name
                name = var_attr.get('name') or prod_attr.get('name')
                if name:
                    ET.SubElement(offer, 'name').text = name
                # Description
                desc = var_attr.get('description') or common_desc
                if desc:
                    ET.SubElement(offer, 'description').text = desc

                # Barcode
                if var_attr.get('barcode'):
                    ET.SubElement(offer, 'barcode').text = var_attr['barcode']

                # Currency and purchase price
                if var_attr.get('currency_code'):
                    ET.SubElement(offer, 'currencyId').text = var_attr['currency_code']
                if var_attr.get('purchased_price') is not None:
                    ET.SubElement(offer, 'purchase_price').text = f"{var_attr['purchased_price']:.2f}"

                # Unit, dimensions, weight
                if var_attr.get('unit_type'):
                    ET.SubElement(offer, 'unit').text = var_attr['unit_type']
                for dim in ('weight', 'length', 'width', 'height'):
                    if var_attr.get(dim) is not None:
                        ET.SubElement(offer, dim).text = str(var_attr[dim])

                # Category
                if var_attr.get('category_id'):
                    ET.SubElement(offer, 'categoryId').text = str(var_attr['category_id'])

                # Custom fields
                for cf in var_attr.get('custom_fields', []):
                    if cf.get('uuid') and cf.get('value'):
                        ET.SubElement(offer, 'param', name=cf['uuid']).text = cf['value']

                # Pictures: variant-level or product-level
                pics = var_attr.get('pictures') or common_pics or []
                for pic_url in pics:
                    ET.SubElement(offer, 'picture').text = pic_url

        xml_bytes = ET.tostring(root, encoding='utf-8', xml_declaration=True)
        return Response(xml_bytes, mimetype='application/xml')

    except Exception as e:
        app.logger.error(f"Error generating feed: {e}")
        return Response("Internal Server Error", status=500)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
