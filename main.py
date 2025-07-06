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
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            if response.status_code == 200:
                return response
            elif response.status_code == 429:
                logger.warning(f"Rate limited. Waiting {delay} sec...")
                time.sleep(delay)
                continue
            elif response.status_code == 401:
                logger.error("401 Unauthorized – check API key")
                break
            else:
                logger.error(f"HTTP {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"Request failed: {e}")
            time.sleep(delay)
    return None

def fetch_products():
    products = []
    page = 1
    per_page = 50
    max_pages = 1000

    while page <= max_pages:
        logger.info(f"📦 Fetching products page {page}")
        resp = safe_request(
            f"{API_URL}/products",
            headers=HEADERS,
            params={
                'per_page': per_page,
                'page': page,
                'filter[is_archived]': 'all'
            }
        )
        if not resp:
            logger.error(f"❌ Failed to fetch page {page}")
            break

        try:
            payload = resp.json()
        except Exception as e:
            logger.error(f"❌ Invalid JSON on page {page}: {e}")
            break

        data = payload.get('data')
        if not isinstance(data, list):
            logger.error(f"❌ Unexpected 'data' format: {type(data)}")
            break

        if not data:
            logger.info(f"✅ No more data on page {page}")
            break

        products.extend(data)
        meta = payload.get('meta', {}).get('pagination', {})
        current = meta.get('current_page') or page
        last = meta.get('last_page')
        has_next = meta.get('has_next_page')

        if last and int(current) >= int(last):
            break
        elif has_next is False:
            break

        page += 1
        time.sleep(0.2)

    logger.info(f"✅ Total products fetched: {len(products)}")
    return products

def fetch_offers_for_product(product_id):
    offers = []
    page = 1
    per_page = 50

    while page <= 100:
        resp = safe_request(
            f"{API_URL}/offers",
            headers=HEADERS,
            params={'filter[product_id]': product_id, 'page': page, 'per_page': per_page}
        )
        if not resp:
            break

        try:
            payload = resp.json()
        except Exception as e:
            logger.error(f"Invalid offers JSON: {e}")
            break

        data = payload.get('data', [])
        if not data:
            break

        offers.extend(data)
        meta = payload.get('meta', {}).get('pagination', {})
        current = meta.get('current_page') or page
        last = meta.get('last_page')
        has_next = meta.get('has_next_page')

        if last and int(current) >= int(last):
            break
        elif has_next is False:
            break

        page += 1
        time.sleep(0.1)

    return offers

def get_all_images(prod, var=None):
    images = []

    def extract(img_obj):
        if isinstance(img_obj, list):
            return img_obj
        elif isinstance(img_obj, str):
            return [img_obj]
        return []

    images += extract(prod.get('pictures') or prod.get('images') or prod.get('gallery') or [])
    if var:
        images += extract(var.get('pictures') or var.get('images') or var.get('gallery') or [])

    seen = set()
    return [x for x in images if x and not (x in seen or seen.add(x))]

def safe_text(text):
    if text is None:
        return ""
    return str(text).strip()

def create_xml_element(parent, tag, text=None, **attrs):
    el = ET.SubElement(parent, tag, **attrs)
    if text:
        el.text = safe_text(text)
    return el

def generate_feed_xml():
    products = fetch_products() or []

    root = ET.Element('yml_catalog', date=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
    shop = ET.SubElement(root, 'shop')
    create_xml_element(shop, 'name', os.getenv('SHOP_NAME', 'Znana'))
    create_xml_element(shop, 'company', os.getenv('COMPANY_NAME', 'Znana'))
    create_xml_element(shop, 'url', os.getenv('SHOP_URL', 'https://yourshop.ua'))

    ET.SubElement(shop, 'currencies')
    ET.SubElement(shop, 'categories')
    offers_el = ET.SubElement(shop, 'offers')

    total = 0

    for product in products:
        prod_attr = product.get('attributes', product)
        product_id = product.get('id')
        variants = fetch_offers_for_product(product_id)

        for var in variants:
            var_attr = var.get('attributes', var)
            sku = var_attr.get('sku') or var_attr.get('article') or var_attr.get('vendor_code') or str(var.get('id'))
            if not sku:
                continue

            try:
                stock = int(float(var_attr.get('stock') or var_attr.get('quantity') or 0))
            except:
                stock = 0

            price = float(var_attr.get('price') or var_attr.get('selling_price') or 0)
            available = 'true' if stock > 0 else 'false'

            offer = ET.SubElement(offers_el, 'offer', id=sku, available=available)
            create_xml_element(offer, 'price', f"{price:.2f}")

            old = var_attr.get('old_price') or var_attr.get('discount_price')
            try:
                if old and float(old) > price:
                    create_xml_element(offer, 'oldprice', f"{float(old):.2f}")
            except:
                pass

            create_xml_element(offer, 'currencyId', var_attr.get('currency_code', 'UAH'))
            create_xml_element(offer, 'stock', str(stock))
            create_xml_element(offer, 'name', var_attr.get('name') or prod_attr.get('name'))
            create_xml_element(offer, 'description', var_attr.get('description') or prod_attr.get('description', ''))
            create_xml_element(offer, 'barcode', var_attr.get('barcode') or var_attr.get('ean'))

            cat_id = var_attr.get('category_id') or prod_attr.get('category_id')
            if cat_id:
                create_xml_element(offer, 'categoryId', str(cat_id))

            for url in get_all_images(prod_attr, var_attr):
                create_xml_element(offer, 'picture', url)

            custom = var_attr.get('custom_fields', [])
            for cf in custom:
                name = cf.get('uuid')
                val = cf.get('value')
                if name and val:
                    create_xml_element(offer, 'param', val, name=name)
                    if 'color' in name.lower():
                        create_xml_element(offer, 'color', val)
                    if 'size' in name.lower():
                        create_xml_element(offer, 'size', val)

            total += 1

    logger.info(f"✅ Generated {total} offers in XML")
    xml_str = ET.tostring(root, encoding='unicode')
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_str}'

@app.route('/feed.xml', methods=['GET'])
def feed():
    try:
        xml = generate_feed_xml()
        return Response(xml, mimetype='application/xml; charset=utf-8')
    except Exception as e:
        logger.error(f"Feed generation error: {e}", exc_info=True)
        return Response("Internal Server Error", status=500)

@app.route('/health', methods=['GET'])
def health():
    return Response("OK", status=200)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
