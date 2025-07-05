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
    """Fetch all products including archived, with robust pagination and error handling"""
    products = []
    page = 1
    per_page = 50  # Reduced from 100 to be more conservative
    max_pages = 1000  # Safety limit to prevent infinite loops

    while page <= max_pages:
        logger.info(f"Fetching products page {page}")
        resp = safe_request(
            f"{API_URL}/products",
            headers=HEADERS,
            params={
                'per_page': per_page,
                'page': page,
                # include archived and hidden products
                'filter[is_archived]': 'all'
            }
        )
        if not resp:
            logger.error(f"Failed to fetch products page {page}")
            break
            
        try:
            payload = resp.json()
        except ValueError as e:
            logger.error(f"Invalid JSON response on page {page}: {e}")
            break
            
        items = payload.get('data', [])
        if not items:
            logger.info(f"No more products found on page {page}")
            break

        products.extend(items)
        logger.info(f"Fetched {len(items)} products from page {page} (total: {len(products)})")

        # Improved pagination handling
        meta = payload.get('meta', {})
        pagination = meta.get('pagination', {})
        
        # Check multiple pagination indicators
        current = pagination.get('current_page') or pagination.get('page') or page
        last = pagination.get('last_page') or pagination.get('total_pages')
        has_next = pagination.get('has_next_page') or pagination.get('next_page')
        
        # Multiple exit conditions
        if last is not None and int(current) >= int(last):
            logger.info(f"Reached last page {last}")
            break
        elif has_next is False:
            logger.info("No more pages available")
            break
        elif len(items) < per_page:
            logger.info(f"Retrieved {len(items)} items, less than per_page {per_page}, assuming end")
            break
        
        page += 1
        time.sleep(0.2)  # Slightly longer delay to avoid rate limiting

    logger.info(f"Total products fetched: {len(products)}")
    return products

def fetch_offers_for_product(product_id):
    """Fetch offers (variants) for a single product with improved error handling"""
    offers = []
    page = 1
    per_page = 50
    max_pages = 100  # Safety limit
    
    while page <= max_pages:
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
            logger.warning(f"Failed to fetch offers for product {product_id} on page {page}")
            break
            
        try:
            payload = response.json()
        except ValueError as e:
            logger.error(f"Invalid JSON response for offers: {e}")
            break
            
        items = payload.get('data', [])
        if not items:
            logger.debug(f"No more offers found for product {product_id} on page {page}")
            break
            
        offers.extend(items)
        
        # Improved pagination for offers
        meta = payload.get('meta', {}).get('pagination', {})
        current = meta.get('current_page') or page
        last = meta.get('last_page')
        has_next = meta.get('has_next_page')
        
        if last is not None and int(current) >= int(last):
            break
        elif has_next is False:
            break
        elif len(items) < per_page:
            break
            
        page += 1
        time.sleep(0.05)  # Small delay
        
    logger.info(f"Fetched {len(offers)} offers for product {product_id}")
    return offers

def get_all_images(product_attr, variant_attr=None):
    """Extract all possible images from product and variant attributes"""
    images = []
    
    # Product images
    product_images = (
        product_attr.get('pictures') or 
        product_attr.get('images') or 
        product_attr.get('photos') or 
        product_attr.get('gallery') or 
        []
    )
    
    if isinstance(product_images, list):
        images.extend(product_images)
    elif isinstance(product_images, str):
        images.append(product_images)
    
    # Variant images (if provided)
    if variant_attr:
        variant_images = (
            variant_attr.get('pictures') or 
            variant_attr.get('images') or 
            variant_attr.get('photos') or 
            variant_attr.get('gallery') or 
            []
        )
        
        if isinstance(variant_images, list):
            images.extend(variant_images)
        elif isinstance(variant_images, str):
            images.append(variant_images)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_images = []
    for img in images:
        if img and img not in seen:
            seen.add(img)
            unique_images.append(img)
    
    return unique_images

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
            
            # Normalize product structure
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
            
            # Common product data
            common_desc = prod_attr.get('description', '') or prod_attr.get('desc', '')
            product_name = prod_attr.get('name', f'Product {product_id}')
            product_price = prod_attr.get('price', 0) or prod_attr.get('selling_price', 0)
            product_stock = prod_attr.get('stock', 0) or prod_attr.get('quantity', 0)
            
            # Fetch variants/offers
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
                
                # Add all product images
                all_images = get_all_images(prod_attr)
                for pic_url in all_images:
                    if pic_url:
                        create_xml_element(offer, 'picture', pic_url)
                
                offer_count += 1
                continue
            
            # Process variants
            for var in variants:
                # Normalize variant structure
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
                
                # SKU is required for variants
                sku = (
                    var_attr.get('sku') or 
                    var_attr.get('article') or 
                    var_attr.get('code') or 
                    var_attr.get('vendor_code') or
                    str(variant_id)  # Fallback to variant ID
                )
                
                if not sku:
                    logger.warning(f"Skipping variant {variant_id} - missing SKU")
                    continue
                
                # Stock handling
                stock = (
                    var_attr.get('stock') or 
                    var_attr.get('quantity') or 
                    var_attr.get('available_quantity') or 
                    var_attr.get('balance') or 
                    var_attr.get('остаток') or 
                    0
                )
                
                try:
                    stock = int(float(stock)) if stock is not None else 0
                except (ValueError, TypeError):
                    stock = 0
                
                available = 'true' if stock > 0 else 'false'
                
                offer = ET.SubElement(offers_elem, 'offer')
                offer.set('id', str(sku))
                offer.set('available', available)
                
                # Price handling
                price = (
                    var_attr.get('price') or 
                    var_attr.get('selling_price') or 
                    var_attr.get('sale_price') or 
                    var_attr.get('retail_price') or 
                    var_attr.get('розничная_цена') or 
                    var_attr.get('цена') or 
                    product_price or 
                    0
                )
                
                try:
                    price = float(price) if price is not None else 0.0
                except (ValueError, TypeError):
                    price = 0.0
                
                create_xml_element(offer, 'price', f"{price:.2f}")
                
                # Old price handling
                discount_price = (
                    var_attr.get('discount_price') or 
                    var_attr.get('old_price') or 
                    var_attr.get('compare_price')
                )
                
                if discount_price:
                    try:
                        discount_price = float(discount_price)
                        if discount_price > price:
                            create_xml_element(offer, 'oldprice', f"{discount_price:.2f}")
                    except (ValueError, TypeError):
                        pass
                
                create_xml_element(offer, 'stock', str(stock))
                create_xml_element(offer, 'name', var_attr.get('name') or product_name)
                
                # Description
                desc = var_attr.get('description') or var_attr.get('desc') or common_desc
                if desc:
                    create_xml_element(offer, 'description', desc)
                
                # Barcode
                barcode = var_attr.get('barcode') or var_attr.get('ean')
                if barcode:
                    create_xml_element(offer, 'barcode', barcode)
                
                create_xml_element(offer, 'currencyId', var_attr.get('currency_code', 'UAH'))
                
                # Purchase price
                purchase_price = (
                    var_attr.get('purchased_price') or 
                    var_attr.get('cost_price') or 
                    var_attr.get('purchase_price')
                )
                
                if purchase_price is not None:
                    try:
                        purchase_price = float(purchase_price)
                        create_xml_element(offer, 'purchase_price', f"{purchase_price:.2f}")
                    except (ValueError, TypeError):
                        pass
                
                # Unit type
                unit_type = var_attr.get('unit_type') or var_attr.get('unit')
                if unit_type:
                    create_xml_element(offer, 'unit', unit_type)
                
                # Dimensions
                for dim in ('weight', 'length', 'width', 'height'):
                    dim_value = var_attr.get(dim)
                    if dim_value is not None:
                        create_xml_element(offer, dim, str(dim_value))
                
                # Category
                category_id = var_attr.get('category_id') or prod_attr.get('category_id')
                if category_id:
                    create_xml_element(offer, 'categoryId', str(category_id))
                
                # Color and size from custom_fields
                color = None
                size = None
                custom_fields = var_attr.get('custom_fields', [])
                if isinstance(custom_fields, list):
                    for cf in custom_fields:
                        if not isinstance(cf, dict):
                            continue
                        uuid = cf.get('uuid', '').lower()
                        value = cf.get('value')
                        if not value:
                            continue
                        if 'color' in uuid or 'колір' in uuid:
                            color = value
                        if 'size' in uuid or 'розмір' in uuid:
                            size = value
                
                if color:
                    create_xml_element(offer, 'color', color)
                if size:
                    create_xml_element(offer, 'size', size)
                
                # Custom fields as parameters
                if isinstance(custom_fields, list):
                    for cf in custom_fields:
                        if isinstance(cf, dict) and cf.get('uuid') and cf.get('value'):
                            param = ET.SubElement(offer, 'param')
                            param.set('name', str(cf['uuid']))
                            param.text = safe_text(cf['value'])
                
                # Add ALL images (both product and variant)
                all_images = get_all_images(prod_attr, var_attr)
                for pic_url in all_images:
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
        response = safe_request(
            f"{API_URL}/products", 
            HEADERS, 
            params={'per_page': 3, 'page': 1}
        )
        if not response:
            return Response("Failed to fetch products", status=500)
        
        payload = response.json()
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
            HEADERS, 
            params={'filter[product_id]': product_id, 'per_page': 3, 'page': 1}
        )
        if not response:
            return Response("Failed to fetch offers", status=500)
        
        payload = response.json()
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

@app.route('/debug/stats', methods=['GET'])
def debug_stats():
    """Debug endpoint to get overall statistics"""
    try:
        import json
        
        # Get total products count
        products_resp = safe_request(
            f"{API_URL}/products", 
            HEADERS, 
            params={'per_page': 1, 'page': 1}
        )
        
        if not products_resp:
            return Response("Failed to fetch products", status=500)
        
        products_payload = products_resp.json()
        products_meta = products_payload.get('meta', {}).get('pagination', {})
        
        stats = {
            'total_products': products_meta.get('total', 'unknown'),
            'total_pages': products_meta.get('last_page', 'unknown'),
            'current_page': products_meta.get('current_page', 1),
            'per_page': products_meta.get('per_page', 'unknown'),
            'api_url': API_URL,
            'has_api_key': bool(API_KEY)
        }
        
        return Response(
            json.dumps(stats, indent=2, ensure_ascii=False), 
            mimetype='application/json; charset=utf-8'
        )
        
    except Exception as e:
        logger.error(f"Debug stats error: {e}", exc_info=True)
        return Response(f"Debug stats error: {str(e)}", status=500)

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
