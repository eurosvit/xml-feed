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
import logging
import time

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load configuration from environment
API_URL = os.getenv('KEYCRM_API_URL', 'https://openapi.keycrm.app/v1')
API_KEY = os.getenv('KEYCRM_API_KEY')
if not API_KEY:
    logger.error('KEYCRM_API_KEY is not set')
    raise RuntimeError('Environment variable KEYCRM_API_KEY is required')

# Common headers for Key CRM API
HEADERS = {
    'Authorization': f'Bearer {API_KEY}',
    'Accept': 'application/json',
    'Content-Type': 'application/json'
}

def safe_request(url, headers, params=None, max_retries=3, delay=1):
    """Make a safe HTTP request with retry logic and error handling"""
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            if response.status_code == 200:
                return response
            elif response.status_code == 429:  # Rate limit
                logger.warning(f"Rate limit hit, waiting {delay * (attempt + 1)} seconds...")
                time.sleep(delay * (attempt + 1))
                continue
            elif response.status_code == 401:
                logger.error("Authentication failed - check API key")
                raise requests.exceptions.HTTPError(f"401 Unauthorized - check API key")
            else:
                logger.error(f"HTTP {response.status_code}: {response.text}")
                response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed (attempt {attempt + 1}): {e}")
            if attempt == max_retries - 1:
                raise
            time.sleep(delay)
    return None

def fetch_products():
    """Fetch all products with improved pagination and error handling"""
    products = []
    page = 1
    per_page = 50  # Reduced page size to avoid timeouts
    while True:
        logger.info(f"Fetching products page {page}")
        response = safe_request(
            f"{API_URL}/products",
            headers=HEADERS,
            params={'per_page': per_page, 'page': page}
        )
        if not response:
            logger.error(f"Failed to fetch products page {page}")
            break
        try:
            payload = response.json()
            logger.debug(f"API Response structure: {list(payload.keys())}")
        except ValueError as e:
            logger.error(f"Invalid JSON response: {e}")
            break
        items = payload.get('data', [])
        if not items:
            logger.info("No more products found")
            break
        if page == 1 and items:
            logger.info(f"First product structure: {items[0]}")
        products.extend(items)
        logger.info(f"Fetched {len(items)} products from page {page}")
        meta = payload.get('meta', {}).get('pagination', {})
        if not meta.get('next_page') or meta.get('current_page') >= meta.get('last_page', 1):
            break
        page += 1
        time.sleep(0.1)  # Small delay to avoid rate limiting
    logger.info(f"Total products fetched: {len(products)}")
    return products

def fetch_offers_for_product(product_id):
    """Fetch offers (variants) for a single product with improved error handling"""
    offers = []
    page = 1
    per_page = 50
    while True:
        logger.debug(f"Fetching offers for product {product_id}, page {page}")
        response = safe_request(
            f"{API_URL}/offers",
            headers=HEADERS,
            params={'filter[product_id]': product_id, 'per_page': per_page, 'page': page}
        )
        if not response:
            logger.warning(f"Failed to fetch offers for product {product_id}")
            break
        try:
            payload = response.json()
            if page == 1 and payload.get('data'):
                logger.debug(f"First offer structure for product {product_id}: {payload['data'][0]}")
        except ValueError as e:
            logger.error(f"Invalid JSON response for offers: {e}")
            break
        items = payload.get('data', [])
        if not items:
            break
        offers.extend(items)
        meta = payload.get('meta', {}).get('pagination', {})
        if not meta.get('next_page') or meta.get('current_page') >= meta.get('last_page', 1):
            break
        page += 1
        time.sleep(0.05)  # Small delay
    logger.info(f"Fetched {len(offers)} offers for product {product_id}")
    return offers

def safe_text(text):
    """Safely convert text for XML, handling None values and encoding"""
    if text is None:
        return ""
    return str(text).strip()

def create_xml_element(parent, tag, text=None, **attrs):
    """Safely create XML element with attributes"""
    element = ET.SubElement(parent, tag, **attrs)
    if text is not None:
        element.text = safe_text(text)
    return element

@app.route('/export/rozetka.xml', methods=['GET'])
def rozetka_feed():
    try:
        logger.info("Starting XML feed generation")
        products = fetch_products()
        if not products:
            logger.warning("No products found")
            return Response("No products found", status=404)
        root = ET.Element('yml_catalog')
        root.set('date', datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
        shop = ET.SubElement(root, 'shop')
        create_xml_element(shop, 'name', os.getenv('SHOP_NAME', 'Znana'))
        create_xml_element(shop, 'company', os.getenv('COMPANY_NAME', 'Znana'))
        create_xml_element(shop, 'url', os.getenv('SHOP_URL', 'https://yourshop.ua'))
        currencies = ET.SubElement(shop, 'currencies')
        ET.SubElement(currencies, 'currency', id='UAH', rate='1')
        categories = ET.SubElement(shop, 'categories')
        offers_elem = ET.SubElement(shop, 'offers')
        offer_count = 0
        for i, product in enumerate(products):
            logger.info(f"Processing product {i+1}/{len(products)}: {product.get('id')}")
            if 'attributes' in product:
                prod_attr = product['attributes']
                product_id = product.get('id')
            elif 'data' in product and isinstance(product['data'], dict):
                prod_attr = product['data'].get('attributes', {})
                product_id = product['data'].get('id') or product.get('id')
            else:
                prod_attr = product
                product_id = product.get('id')
            logger.debug(f"Product {product_id} attributes keys: {list(prod_attr.keys())}")
            common_desc = prod_attr.get('description', '') or prod_attr.get('desc', '')
            common_pics = prod_attr.get('pictures', []) or prod_attr.get('images', [])
            product_name = prod_attr.get('name', f'Product {product_id}')
            product_price = prod_attr.get('price', 0) or prod_attr.get('selling_price', 0)
            product_stock = prod_attr.get('stock', 0) or prod_attr.get('quantity', 0)
            variants = fetch_offers_for_product(product_id)
            if not variants:
                logger.info(f"No variants found for product {product_id}, using product data")
                offer = ET.SubElement(offers_elem, 'offer')
                offer.set('id', str(product_id))
                try:
                    stock = int(product_stock) if product_stock is not None else 0
                except (ValueError, TypeError):
                    stock = 0
                offer.set('available', 'true' if stock > 0 else 'false')
                create_xml_element(offer, 'name', product_name)
                if common_desc:
                    create_xml_element(offer, 'description', common_desc)
                try:
                    price = float(product_price) if product_price is not None else 0.0
                except (ValueError, TypeError):
                    price = 0.0
                create_xml_element(offer, 'price', f"{price:.2f}")
                create_xml_element(offer, 'stock', str(stock))
                create_xml_element(offer, 'currencyId', 'UAH')
                if isinstance(common_pics, list):
                    for pic_url in common_pics:
                        if pic_url:
                            create_xml_element(offer, 'picture', pic_url)
                offer_count += 1
                continue
            for var in variants:
                if 'attributes' in var:
                    var_attr = var['attributes']
                    variant_id = var.get('id')
                elif 'data' in var and isinstance(var['data'], dict):
                    var_attr = var['data'].get('attributes', {})
                    variant_id = var['data'].get('id') or var.get('id')
                else:
                    var_attr = var
                    variant_id = var.get('id')
                logger.debug(f"Variant {variant_id} attributes keys: {list(var_attr.keys())}")
                sku = (var_attr.get('sku') or var_attr.get('article') or var_attr.get('code') or var_attr.get('vendor_code'))
                if not sku:
                    logger.warning(f"Skipping variant {variant_id} - missing SKU")
                    continue
                stock = (var_attr.get('stock') or var_attr.get('quantity') or var_attr.get('available_quantity') or var_attr.get('balance') or var_attr.get('остаток') or 0)
                try:
                    stock = int(float(stock)) if stock is not None else 0
                except (ValueError, TypeError):
                    stock = 0
                available = 'true' if stock > 0 else 'false'
                offer = ET.SubElement(offers_elem, 'offer')
                offer.set('id', str(sku))
                offer.set('available', available)
                price = (var_attr.get('price') or var_attr.get('selling_price') or var_attr.get('sale_price') or var_attr.get('retail_price') or var_attr.get('розничная_цена') or var_attr.get('цена') or product_price or 0)
                try:
                    price = float(price) if price is not None else 0.0
                except (ValueError, TypeError):
                    price = 0.0
                create_xml_element(offer, 'price', f"{price:.2f}")
                discount_price = (var_attr.get('discount_price') or var_attr.get('old_price') or var_attr.get('compare_price'))
                if discount_price:
                    try:
                        discount_price = float(discount_price)
                        if discount_price > price:
                            create_xml_element(offer, 'oldprice', f"{discount_price:.2f}")
                    except (ValueError, TypeError):
                        pass
                create_xml_element(offer, 'stock', str(stock))
                create_xml_element(offer, 'name', var_attr.get('name') or product_name)
                desc = (var_attr.get('description') or var_attr.get('desc') or common_desc)
                if desc:
                    create_xml_element(offer, 'description', desc)
                barcode = var_attr.get('barcode') or var_attr.get('ean')
                if barcode:
                    create_xml_element(offer, 'barcode', barcode)
                create_xml_element(offer, 'currencyId', var_attr.get('currency_code', 'UAH'))
                purchase_price = (var_attr.get('purchased_price') or var_attr.get('cost_price') or var_attr.get('purchase_price'))
                if purchase_price is not None:
                    try:
                        purchase_price = float(purchase_price)
                        create_xml_element(offer, 'purchase_price', f"{purchase_price:.2f}")
                    except (ValueError, TypeError):
                        pass
                unit_type = var_attr.get('unit_type') or var_attr.get('unit')
                if unit_type:
                    create_xml_element(offer, 'unit', unit_type)
                for dim in ('weight', 'length', 'width', 'height'):
                    dim_value = var_attr.get(dim)
                    if dim_value is not None:
                        create_xml_element(offer, dim, str(dim_value))
                category_id = (var_attr.get('category_id') or prod_attr.get('category_id'))
                if category_id:
                    create_xml_element(offer, 'categoryId', str(category_id))
                custom_fields = var_attr.get('custom_fields', [])
                if isinstance(custom_fields, list):
                    for cf in custom_fields:
                        if isinstance(cf, dict) and cf.get('uuid') and cf.get('value'):
                            param = ET.SubElement(offer, 'param')
                            param.set('name', str(cf['uuid']))
                            param.text = safe_text(cf['value'])
                pics = (var_attr.get('pictures') or var_attr.get('images') or common_pics or [])
                if isinstance(pics, list):
                    for pic_url in pics:
                        if pic_url:
                            create_xml_element(offer, 'picture', pic_url)
                offer_count += 1
        logger.info(f"Generated XML feed with {offer_count} offers")
        xml_str = ET.tostring(root, encoding='unicode', xml_declaration=False)
        xml_response = f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_str}'
        return Response(xml_response, mimetype='application/xml; charset=utf-8')
    except Exception as e:
        logger.error(f"Error generating feed: {e}", exc_info=True)
        return Response(f"Internal Server Error: {str(e)}", status=500)

@app.route('/debug/products', methods=['GET'])
def debug_products():
    """Debug endpoint to see raw product data structure"""
    try:
        logger.info("Debug: Fetching first few products")
        response = safe_request(f"{API_URL}/products", HEADERS, params={'per_page': 3, 'page': 1})
        if not response:
            return Response("Failed to fetch products", status=500)
        payload = response.json()
        import json
        debug_info = { 'api_response_keys': list(payload.keys()), 'first_product': payload.get('data', [{}])[0] if payload.get('data') else None, 'meta': payload.get('meta', {}), 'total_products': len(payload.get('data', [])) }
        return Response(json.dumps(debug_info, indent=2, ensure_ascii=False), mimetype='application/json; charset=utf-8')
    except Exception as e:
        logger.error(f"Debug error: {e}", exc_info=True)
        return Response(f"Debug error: {str(e)}", status=500)

@app.route('/debug/offers/<int:product_id>', methods=['GET'])
def debug_offers(product_id):
    """Debug endpoint to see raw offers data structure"""
    try:
        logger.info(f"Debug: Fetching offers for product {product_id}")
        response = safe_request(f"{API_URL}/offers", HEADERS, params={'filter[product_id]': product_id, 'per_page': 3, 'page': 1})
        if not response:
            return Response("Failed to fetch offers", status=500)
        payload = response.json()
        import json
        debug_info = { 'api_response_keys': list(payload.keys()), 'first_offer': payload.get('data', [{}])[0] if payload.get('data') else None, 'meta': payload.get('meta', {}), 'total_offers': len(payload.get('data', [])) }
        return Response(json.dumps(debug_info, indent=2, ensure_ascii=False), mimetype='application/json; charset=utf-8')
    except Exception as e:
        logger.error(f"Debug error: {e}", exc_info=True)
        return Response(f"Debug error: {str(e)}", status=500)

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return Response("OK", status=200)

@app.errorhandler(500)
def internal_error(error):
    return Response("Internal Server Error", status=500)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
