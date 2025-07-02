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

# Конфігурація через змінні оточення
API_URL = os.getenv('KEYCRM_API_URL', 'https://openapi.keycrm.app/v1')
API_KEY = os.getenv('KEYCRM_API_KEY')
if not API_KEY:
    app.logger.error('KEYCRM_API_KEY is not set')
    raise RuntimeError('Environment variable KEYCRM_API_KEY is required')

HEADERS = {
    'Authorization': f'Bearer {API_KEY}',
    'Accept': 'application/json'
}

# Отримати всі продукти (кожен продукт — окремий варіант)
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

@app.route('/export/rozetka.xml', methods=['GET'])
def rozetka_feed():
    try:
        products = fetch_products()
        root = ET.Element('yml_catalog', date=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
        shop = ET.SubElement(root, 'shop')
        ET.SubElement(shop, 'name').text = os.getenv('SHOP_NAME', 'Znana')
        ET.SubElement(shop, 'company').text = os.getenv('COMPANY_NAME', 'Znana')
        ET.SubElement(shop, 'url').text = os.getenv('SHOP_URL', 'Znana Maternity')

        currencies = ET.SubElement(shop, 'currencies')
        ET.SubElement(currencies, 'currency', id='UAH', rate='1')

        offers = ET.SubElement(shop, 'offers')
        for p in products:
            sku = p.get('sku')
            if not sku:
                continue
            available = 'true' if p.get('stock', 0) > 0 else 'false'
            offer = ET.SubElement(offers, 'offer', id=sku, available=available)

            # Базові поля
            ET.SubElement(offer, 'price').text = f"{p.get('price', 0):.2f}"
            ET.SubElement(offer, 'stock').text = str(p.get('stock', 0))

            # Назва, опис
            name = p.get('name')
            if name:
                ET.SubElement(offer, 'name').text = name
            description = p.get('description')
            if description:
                ET.SubElement(offer, 'description').text = description

            # Штрихкод
            barcode = p.get('barcode')
            if barcode:
                ET.SubElement(offer, 'barcode').text = barcode

            # Валюта та ціна закупівлі
            currency = p.get('currency_code')
            if currency:
                ET.SubElement(offer, 'currencyId').text = currency
            purchase_price = p.get('purchased_price')
            if purchase_price is not None:
                ET.SubElement(offer, 'purchase_price').text = f"{purchase_price:.2f}"

            # Розміри та вага
            unit = p.get('unit_type')
            if unit:
                ET.SubElement(offer, 'unit').text = unit
            for dim in ('weight', 'length', 'width', 'height'):
                val = p.get(dim)
                if val is not None:
                    ET.SubElement(offer, dim).text = str(val)

            # Категорія
            cat = p.get('category_id')
            if cat:
                ET.SubElement(offer, 'categoryId').text = str(cat)

            # Кастомні поля (наприклад, color/size)
            for cf in p.get('custom_fields', []):
                uuid = cf.get('uuid')
                val = cf.get('value')
                if uuid and val:
                    ET.SubElement(offer, 'param', name=uuid).text = val

            # Фото
            for pic_url in p.get('pictures', []):
                ET.SubElement(offer, 'picture').text = pic_url

        xml_bytes = ET.tostring(root, encoding='utf-8', xml_declaration=True)
        return Response(xml_bytes, mimetype='application/xml')
    except Exception as e:
        app.logger.error(f"Error generating feed: {e}")
        return Response("Internal Server Error", status=500)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
