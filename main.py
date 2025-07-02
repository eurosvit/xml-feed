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
        
        # Simple request without include parameter
        response = safe_request(
            f"{API_URL}/products",
            headers=HEADERS,
            params={
                'per_page': per_page, 
                'page': page
            }
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
            
        # Log first product structure for debugging
        if page == 1 and items:
            logger.info(f"First product structure: {items[0]}")
            
        products.extend(items)
        logger.info(f"Fetched {len(items)} products from page {page}")
        
        # Check pagination
        meta = payload.get('meta', {})
        pagination = meta.get('pagination', {})
        
        if not pagination.get('next_page') or pagination.get('current_page') >= pagination.get('last_page', 1):
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
            params={
                'filter[product_id]': product_id,
                'per_page': per_page,
                'page': page
            }
        )
        
        if not response:
            logger.warning(f"Failed to fetch offers for product {product_id}")
            break
            
        try:
            payload = response.json()
            # Log first offer structure for debugging
            if page == 1 and payload.get('data') and len(payload['data']) > 0:
                logger.debug(f"First offer structure for product {product_id}: {payload['data'][0]}")
        except ValueError as e:
            logger.error(f"Invalid JSON response for offers: {e}")
            break
            
        items = payload.get('data', [])
        if not items:
            break
            
        offers.extend(items)
        
        # Check pagination
        meta = payload.get('meta', {})
        pagination = meta.get('pagination', {})
        
        if not pagination.get('next_page') or pagination.get('current_page') >= pagination.get('last_page', 1):
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

def extract_color_and_size(var_attr, prod_attr=None):
    """
    Extract color and size from variant attributes or custom fields
    Returns tuple (color, size)
    """
    color = None
    size = None
    
    # Try to get color and size from direct attributes first
    color_fields = ['color', 'colour', 'колір', 'цвет', 'Color', 'COLOUR']
    size_fields = ['size', 'розмір', 'размер', 'Size', 'SIZE']
    
    # Check direct attributes
    for field in color_fields:
        if var_attr.get(field):
            color = var_attr[field]
            break
    
    for field in size_fields:
        if var_attr.get(field):
            size = var_attr[field]
            break
    
    # Check custom fields if not found in direct attributes
    custom_fields = var_attr.get('custom_fields', [])
    if isinstance(custom_fields, list):
        for cf in custom_fields:
            if isinstance(cf, dict):
                field_name = str(cf.get('name', '') or cf.get('uuid', '')).lower()
                field_value = cf.get('value')
                
                if field_value and any(color_field.lower() in field_name for color_field in color_fields):
                    color = field_value
                elif field_value and any(size_field.lower() in field_name for size_field in size_fields):
                    size = field_value
    
    # Fallback to product-level attributes if available
    if not color and prod_attr:
        for field in color_fields:
            if prod_attr.get(field):
                color = prod_attr[field]
                break
    
    if not size and prod_attr:
        for field in size_fields:
            if prod_attr.get(field):
                size = prod_attr[field]
                break
    
    return color, size

def add_color_size_params(offer_element, color, size):
    """Add color and size as XML parameters"""
    if color:
        param = ET.SubElement(offer_element, 'param')
        param.set('name', 'Колір')
        param.text = safe_text(color)
        logger.debug(f"Added color parameter: {color}")
    
    if size:
        param = ET.SubElement(offer_element, 'param')
        param.set('name', 'Розмір')
        param.text = safe_text(size)
        logger.debug(f"Added size parameter: {size}")

@app.route('/export/rozetka.xml', methods=['GET'])
def rozetka_feed():
    try:
        logger.info("Starting XML feed generation")
        
        # Retrieve all products
        products = fetch_products()
        
        if not products:
            logger.warning("No products found")
            return Response("No products found", status=404)

        # Build YML catalog root
        root = ET.Element('yml_catalog')
        root.set('date', datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
        
        shop = ET.SubElement(root, 'shop')
        create_xml_element(shop, 'name', os.getenv('SHOP_NAME', 'Znana'))
        create_xml_element(shop, 'company', os.getenv('COMPANY_NAME', 'Znana'))
        create_xml_element(shop, 'url', os.getenv('SHOP_URL', 'https://yourshop.ua'))

        # Currencies
        currencies = ET.SubElement(shop, 'currencies')
        ET.SubElement(currencies, 'currency', id='UAH', rate='1')

        # Categories (if needed)
        categories = ET.SubElement(shop, 'categories')
        
        # Offers section
        offers_elem = ET.SubElement(shop, 'offers')
        offer_count = 0
        
        for i, product in enumerate(products):
            logger.info(f"Processing product {i+1}/{len(products)}: {product.get('id')}")
            
            # Get product data safely - handle different API response structures
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
            
            # Common product-level data
            common_desc = prod_attr.get('description', '') or prod_attr.get('desc', '')
            common_pics = prod_attr.get('pictures', []) or prod_attr.get('images', [])
            product_name = prod_attr.get('name', f'Product {product_id}')
            
            # Try to get price from product level
            product_price = prod_attr.get('price', 0) or prod_attr.get('selling_price', 0)
            product_stock = prod_attr.get('stock', 0) or prod_attr.get('quantity', 0)
            
            # Fetch all variant offers
            variants = fetch_offers_for_product(product_id)
            
            if not variants:
                # If no variants, create offer from product data
                logger.info(f"No variants found for product {product_id}, using product data")
                offer = ET.SubElement(offers_elem, 'offer')
                offer.set('id', str(product_id))
                
                # Determine availability
                try:
                    stock = int(product_stock) if product_stock is not None else 0
                except (ValueError, TypeError):
                    stock = 0
                offer.set('available', 'true' if stock > 0 else 'false')
                
                create_xml_element(offer, 'name', product_name)
                if common_desc:
                    create_xml_element(offer, 'description', common_desc)
                
                # Price handling
                try:
                    price = float(product_price) if product_price is not None else 0.0
                except (ValueError, TypeError):
                    price = 0.0
                create_xml_element(offer, 'price', f"{price:.2f}")
                create_xml_element(offer, 'stock', str(stock))
                create_xml_element(offer, 'currencyId', 'UAH')
                
                # Add color and size for product-level offer
                color, size = extract_color_and_size(prod_attr)
                add_color_size_params(offer, color, size)
                
                # Add pictures
                if isinstance(common_pics, list):
                    for pic_url in common_pics:
                        if pic_url:
                            create_xml_element(offer, 'picture', pic_url)
                
                offer_count += 1
                continue
            
            for var in variants:
                # Handle different variant structures
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
                
                # Get SKU or use variant ID - SKU обов'язково для ідентифікації
                sku = (var_attr.get('sku') or 
                       var_attr.get('article') or 
                       var_attr.get('code') or
                       var_attr.get('vendor_code'))
                
                if not sku:
                    logger.warning(f"ПРОПУСКАЄМО variant {variant_id} - відсутній SKU!")
                    logger.debug(f"Доступні поля варіанта: {list(var_attr.keys())}")
                    continue
                
                # Check availability and stock - пріоритет stock > quantity > available_quantity
                stock = (var_attr.get('stock') or 
                        var_attr.get('quantity') or 
                        var_attr.get('available_quantity') or
                        var_attr.get('balance') or
                        var_attr.get('остаток') or 0)
                
                try:
                    stock = int(float(stock)) if stock is not None else 0
                except (ValueError, TypeError):
                    stock = 0
                    
                logger.debug(f"SKU {sku}: stock={stock}")
                available = 'true' if stock > 0 else 'false'
                
                # Create offer element
                offer = ET.SubElement(offers_elem, 'offer')
                offer.set('id', str(sku))
                offer.set('available', available)

                # Price handling - розширений пошук по всіх можливих полях ціни
                price = (var_attr.get('price') or 
                        var_attr.get('selling_price') or 
                        var_attr.get('sale_price') or
                        var_attr.get('retail_price') or
                        var_attr.get('розничная_цена') or
                        var_attr.get('цена') or
                        product_price or 0)
                
                try:
                    price = float(price) if price is not None else 0.0
                except (ValueError, TypeError):
                    price = 0.0
                
                logger.debug(f"SKU {sku}: price={price}")
                
                if price <= 0:
                    logger.warning(f"SKU {sku}: ціна = 0, доступні поля: {list(var_attr.keys())}")
                
                create_xml_element(offer, 'price', f"{price:.2f}")
                
                # Discount price if available
                discount_price = (var_attr.get('discount_price') or 
                                var_attr.get('old_price') or 
                                var_attr.get('compare_price'))
                if discount_price:
                    try:
                        discount_price = float(discount_price)
                        if discount_price > price:
                            create_xml_element(offer, 'oldprice', f"{discount_price:.2f}")
                    except (ValueError, TypeError):
                        pass
                
                # Stock
                create_xml_element(offer, 'stock', str(stock))

                # Name and description
                name = var_attr.get('name') or product_name
                create_xml_element(offer, 'name', name)
                
                desc = (var_attr.get('description') or 
                       var_attr.get('desc') or 
                       common_desc)
                if desc:
                    create_xml_element(offer, 'description', desc)

                # Barcode
                barcode = var_attr.get('barcode') or var_attr.get('ean')
                if barcode:
                    create_xml_element(offer, 'barcode', barcode)

                # Currency
                currency = var_attr.get('currency_code', 'UAH')
                create_xml_element(offer, 'currencyId', currency)
                
                # Purchase price
                purchase_price = (var_attr.get('purchased_price') or 
                                var_attr.get('cost_price') or 
                                var_attr.get('purchase_price'))
                if purchase_price is not None:
                    try:
                        purchase_price = float(purchase_price)
                        create_xml_element(offer, 'purchase_price', f"{purchase_price:.2f}")
                    except (ValueError, TypeError):
                        pass

                # Unit and dimensions
                unit_type = var_attr.get('unit_type') or var_attr.get('unit')
                if unit_type:
                    create_xml_element(offer, 'unit', unit_type)
                
                for dim in ('weight', 'length', 'width', 'height'):
                    dim_value = var_attr.get(dim)
                    if dim_value is not None:
                        create_xml_element(offer, dim, str(dim_value))

                # Category
                category_id = (var_attr.get('category_id') or 
                             prod_attr.get('category_id'))
                if category_id:
                    create_xml_element(offer, 'categoryId', str(category_id))

                # ГОЛОВНЕ НОВОВВЕДЕННЯ: Додаємо колір та розмір як параметри
                color, size = extract_color_and_size(var_attr, prod_attr)
                add_color_size_params(offer, color, size)

                # Custom fields as parameters (крім кольору та розміру, які вже додані окремо)
                custom_fields = var_attr.get('custom_fields', [])
                if isinstance(custom_fields, list):
                    for cf in custom_fields:
                        if isinstance(cf, dict) and cf.get('uuid') and cf.get('value'):
                            field_name = str(cf.get('name', '') or cf.get('uuid', '')).lower()
                            
                            # Пропускаємо колір та розмір, оскільки вони вже додані окремо
                            if not any(color_field.lower() in field_name for color_field in ['color', 'colour', 'колір', 'цвет']):
                                if not any(size_field.lower() in field_name for size_field in ['size', 'розмір', 'размер']):
                                    param = ET.SubElement(offer, 'param')
                                    param.set('name', str(cf.get('name', cf['uuid'])))
                                    param.text = safe_text(cf['value'])

                # Pictures: variant-level or fallback to product-level
                pics = (var_attr.get('pictures') or 
                       var_attr.get('images') or 
                       common_pics or [])
                       
                if isinstance(pics, list):
                    for pic_url in pics:
                        if pic_url:
                            create_xml_element(offer, 'picture', pic_url)
                
                offer_count += 1

        logger.info(f"Generated XML feed with {offer_count} offers")
        
        # Serialize XML and return response
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
        
        response = safe_request(
            f"{API_URL}/products",
            headers=HEADERS,
            params={
                'per_page': 3,
                'page': 1
            }
        )
        
        if not response:
            return Response("Failed to fetch products", status=500)
        
        payload = response.json()
        
        # Pretty print the structure
        import json
        debug_info = {
            'api_response_keys': list(payload.keys()),
            'first_product': payload.get('data', [{}])[0] if payload.get('data') else None,
            'meta': payload.get('meta', {}),
            'total_products': len(payload.get('data', []))
        }
        
        return Response(
            json.dumps(debug_info, indent=2, ensure_ascii=False),
            mimetype='application/json; charset=utf-8'
        )
        
    except Exception as e:
        logger.error(f"Debug error: {e}", exc_info=True)
        return Response(f"Debug error: {str(e)}", status=500)

@app.route('/debug/offers/<int:product_id>', methods=['GET'])
def debug_offers(product_id):
    """Debug endpoint to see raw offers data structure"""
    try:
        logger.info(f"Debug: Fetching offers for product {product_id}")
        
        response = safe_request(
            f"{API_URL}/offers",
            headers=HEADERS,
            params={
                'filter[product_id]': product_id,
                'per_page': 3,
                'page': 1
            }
        )
        
        if not response:
            return Response("Failed to fetch offers", status=500)
        
        payload = response.json()
        
        # Pretty print the structure
        import json
        debug_info = {
            'api_response_keys': list(payload.keys()),
            'first_offer': payload.get('data', [{}])[0] if payload.get('data') else None,
            'meta': payload.get('meta', {}),
            'total_offers': len(payload.get('data', []))
        }
        
        return Response(
            json.dumps(debug_info, indent=2, ensure_ascii=False),
            mimetype='application/json; charset=utf-8'
        )
        
    except Exception as e:
        logger.error(f"Debug error: {e}", exc_info=True)
        return Response(f"Debug error: {str(e)}", status=500)

@app.route('/debug/color-size/<int:product_id>', methods=['GET'])
def debug_color_size(product_id):
    """Debug endpoint to see color and size extraction for a specific product"""
    try:
        logger.info(f"Debug: Checking color/size for product {product_id}")
        
        # Fetch offers for the product
        variants = fetch_offers_for_product(product_id)
        
        debug_info = {
            'product_id': product_id,
            'variants_count': len(variants),
            'variants_analysis': []
        }
        
        for var in variants[:3]:  # Only first 3 for debug
            if 'attributes' in var:
                var_attr = var['attributes']
                variant_id = var.get('id')
            else:
                var_attr = var
                variant_id = var.get('id')
            
            color, size = extract_color_and_size(var_attr)
            
            debug_info['variants_analysis'].append({
                'variant_id': variant_id,
                'extracted_color': color,
                'extracted_size': size,
                'all_attributes': list(var_attr.keys()),
                'custom_fields': var_attr.get('custom_fields', [])
            })
        
        import json
        return Response(
            json.dumps(debug_info, indent=2, ensure_ascii=False),
            mimetype='application/json; charset=utf-8'
        )
        
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
