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

# Змінні оточення
API_URL = os.getenv('KEYCRM_API_URL', 'https://openapi.keycrm.app/v1')
API_KEY = os.getenv('KEYCRM_API_KEY')
if not API_KEY:
    app.logger.error("KEYCRM_API_KEY is not set")
    raise RuntimeError("Environment variable KEYCRM_API_KEY is required")

# Заголовки для всіх запитів до Key CRM
HEADERS = {
    'Authorization': f'Bearer {API_KEY}',
    'Accept': 'application/json'
}

# Отримати перелік продуктів з Key CRM
def fetch_products():
    products = []
    page = 1
    per_page = 100
    while True:
        resp = requests.get(f"{API_URL}/products", headers=HEADERS, params={'per_page': per_page, 'page': page})
        if resp.status_code != 200:
            app.logger.error(f"Key CRM /products error {resp.status_code}: {resp.text}")
            resp.raise_for_status()
        result = resp.json().get('data', [])
        if not result:
            break
        products.extend(result)
        # Перевіряємо, чи є наступна сторінка (якщо є meta.pagination.next_page)
        meta = resp.json().get('meta', {}).get('pagination', {})
        if not meta.get('next_page'):
            break
        page += 1
    return products

# Отримати варіанти продукту
def fetch_variants(product_id):
    resp = requests.get(f"{API_URL}/products/{product_id}/variants", headers=HEADERS)
    if resp.status_code != 200:
        app.logger.error(f"Key CRM /products/{product_id}/variants error {resp.status_code}: {resp.text}")
        resp.raise_for_status()
    return resp.json().get('data', [])

# Отримати фото продукту
def fetch_images(product_id):
    resp = requests.get(f"{API_URL}/products/{product_id}/images", headers=HEADERS)
    if resp.status_code != 200:
        app.logger.warning(f"No images for product {product_id}: {resp.status_code}")
        return []
    return resp.json().get('data', [])

# Ендпоінт XML-фіда
@app.route('/export/rozetka.xml', methods=['GET'])
def rozetka_feed():
    products = fetch_products()

    root = ET.Element('yml_catalog', date=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
    shop = ET.SubElement(root, 'shop')
    ET.SubElement(shop, 'name').text = os.getenv('SHOP_NAME', 'Ваша Компанія')
    ET.SubElement(shop, 'company').text = os.getenv('COMPANY_NAME', 'Ваша Компанія LLC')
    ET.SubElement(shop, 'url').text = os.getenv('SHOP_URL', 'https://yourshop.ua')

    currencies = ET.SubElement(shop, 'currencies')
    ET.SubElement(currencies, 'currency', id='UAH', rate='1')

    offers = ET.SubElement(shop, 'offers')
    for p in products:
        # Загальний опис та фото продукту
        product_desc = p.get('description', '')
        product_image_objs = fetch_images(p['id'])
        product_images = [img.get('url') or img.get('src') for img in product_image_objs if img.get('url') or img.get('src')]

        for v in fetch_variants(p['id']):
            sku = v.get('sku')
            if not sku:
                continue
            available = 'true' if v.get('stock', 0) > 0 else 'false'
            offer = ET.SubElement(offers, 'offer', id=sku, available=available)

            ET.SubElement(offer, 'price').text = f"{v.get('price', 0):.2f}"
            ET.SubElement(offer, 'stock').text = str(v.get('stock', 0))

            if v.get('color'):
                ET.SubElement(offer, 'param', name='color').text = v['color']
            if v.get('size'):
                ET.SubElement(offer, 'param', name='size').text = v['size']

            # Опис варіанту або загальний
            desc = v.get('description') or product_desc
            if desc:
                ET.SubElement(offer, 'description').text = desc

            # Фото: спочатку варіант, інакше фото продукту
            variant_images = [img.get('url') or img.get('src') for img in v.get('images', []) if img.get('url') or img.get('src')]
            images = variant_images or product_images
            for url in images:
                ET.SubElement(offer, 'picture').text = url

    xml_bytes = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    return Response(xml_bytes, mimetype='application/xml')

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
