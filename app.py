from flask import Flask, Response
import os, requests
import xml.etree.ElementTree as ET
from datetime import datetime

app = Flask(__name__)

API_URL = os.getenv('KEYCRM_API_URL', 'https://api.keycrm.app/v1')
API_KEY = os.getenv('NzVkMmJhODVjYzQ5MDQ1ZDdkMjk5YWE2NTY4MmRlNDJhMTZiNzYwMA')

def fetch_all_products():
    headers = {
        'Authorization': f'Bearer {API_KEY}',
        'Accept': 'application/json'
    }
    params = {
        'include': 'variants',  # щоб у відповіді були варіанти товарів
        'per_page': 100,        # регулюйте під розмір каталогу
        'page': 1
    }
    all_products = []
    while True:
        resp = requests.get(f"{API_URL}/products", headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        all_products.extend(data['data'])
        if not data['meta']['pagination']['next_page']:
            break
        params['page'] += 1
    return all_products

@app.route('/export/rozetka.xml', methods=['GET'])
def rozetka_feed():
    products = fetch_all_products()

    root = ET.Element('yml_catalog', date=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
    shop = ET.SubElement(root, 'shop')
    ET.SubElement(shop, 'name').text = 'Znana'
    ET.SubElement(shop, 'company').text = 'Znana'
    ET.SubElement(shop, 'url').text = 'znana'

    currencies = ET.SubElement(shop, 'currencies')
    ET.SubElement(currencies, 'currency', id='UAH', rate='1')

    offers = ET.SubElement(shop, 'offers')
    for p in products:
        for v in p.get('variants', []):
            offer = ET.SubElement(offers, 'offer', 
                                  id=v['sku'],
                                  available=str(v['stock'] > 0).lower())
            ET.SubElement(offer, 'price').text = f"{v['price']:.2f}"
            ET.SubElement(offer, 'stock').text = str(v['stock'])
            # Якщо у Key CRM у варіанті є атрибути color/size:
            if 'color' in v:
                ET.SubElement(offer, 'param', name='color').text = v['color']
            if 'size' in v:
                ET.SubElement(offer, 'param', name='size').text = v['size']

    xml_bytes = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    return Response(xml_bytes, mimetype='application/xml')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8080)))
