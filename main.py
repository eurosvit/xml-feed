from flask import Flask, Response
import os
import requests
import xml.etree.ElementTree as ET
from datetime import datetime

app = Flask(__name__)

# Налаштування через змінні оточення
API_URL = os.getenv('KEYCRM_API_URL', 'https://api.keycrm.app/v1')
API_KEY = os.getenv('NzVkMmJhODVjYzQ5MDQ1ZDdkMjk5YWE2NTY4MmRlNDJhMTZiNzYwMA')

# Функція для отримання всіх товарів із Key CRM (з пагінацією)
def fetch_all_products():
    headers = {
        'Authorization': f'Bearer {API_KEY}',
        'Accept': 'application/json'
    }
    params = {
        'include': 'variants,images',  # щоб у відповіді були варіанти та фото
        'per_page': 100,
        'page': 1
    }
    all_products = []
    while True:
        resp = requests.get(f"{API_URL}/products", headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        products = data.get('data', [])
        all_products.extend(products)
        pagination = data.get('meta', {}).get('pagination', {})
        if not pagination.get('next_page'):
            break
        params['page'] += 1
    return all_products

# Ендпоінт XML-фіда для Prom/Rozetka
@app.route('/export/rozetka.xml', methods=['GET'])
def rozetka_feed():
    products = fetch_all_products()

    # Коренева структура YML
    root = ET.Element('yml_catalog', date=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
    shop = ET.SubElement(root, 'shop')
    ET.SubElement(shop, 'name').text = os.getenv('SHOP_NAME', 'Ваша Компанія')
    ET.SubElement(shop, 'company').text = os.getenv('COMPANY_NAME', 'Ваша Компанія LLC')
    ET.SubElement(shop, 'url').text = os.getenv('SHOP_URL', 'https://yourshop.ua')

    currencies = ET.SubElement(shop, 'currencies')
    ET.SubElement(currencies, 'currency', id='UAH', rate='1')

    offers = ET.SubElement(shop, 'offers')
    for p in products:
        # Опис та фото товару загалом
        product_desc = p.get('description', '')
        product_images = [img.get('url') or img.get('src') for img in p.get('images', []) if img.get('url') or img.get('src')]

        for v in p.get('variants', []):
            sku = v.get('sku')
            if not sku:
                continue
            available = 'true' if v.get('stock', 0) > 0 else 'false'
            offer = ET.SubElement(offers, 'offer', id=sku, available=available)

            # Ціна та залишок
            ET.SubElement(offer, 'price').text = f"{v.get('price', 0):.2f}"
            ET.SubElement(offer, 'stock').text = str(v.get('stock', 0))

            # Параметри колір/розмір
            if v.get('color'):
                ET.SubElement(offer, 'param', name='color').text = v['color']
            if v.get('size'):
                ET.SubElement(offer, 'param', name='size').text = v['size']

            # Опис (спочатку для варіанту, інакше загальний)
            desc = v.get('description') or product_desc
            if desc:
                ET.SubElement(offer, 'description').text = desc

            # Фото (спочатку фото варіанту, інакше загальні фото товару)
            variant_images = [img.get('url') or img.get('src') for img in v.get('images', []) if img.get('url') or img.get('src')]
            images = variant_images or product_images
            for url in images:
                ET.SubElement(offer, 'picture').text = url

    # Повертаємо XML
    xml_bytes = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    return Response(xml_bytes, mimetype='application/xml')

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
