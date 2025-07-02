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
        except ValueError as e:
            logger.error(f"Invalid JSON response: {e}")
            break
            
        items = payload.get('data', [])
        if not items:
            logger.info("No more products found")
            break
            
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
            
            # Get product data safely
            product_data = product.get('data', {}) if isinstance(product.get('data'), dict) else {}
            prod_attr = product_data.get('attributes', {}) or product.get('attributes', {})
            
            # Common product-level data
            common_desc = prod_attr.get('description', '')
            common_pics = prod_attr.get('pictures', [])
            product_name = prod_attr.get('name', f'Product {product.get("id")}')

            # Fetch all variant offers
            variants = fetch_offers_for_product(product.get('id'))
            
            if not variants:
                # If no variants, create offer from product data
                logger.info(f"No variants found for product {product.get('id')}, using product data")
                offer = ET.SubElement(offers_elem, 'offer')
                offer.set('id', str(product.get('id')))
                offer.set('available', 'true')
                
                create_xml_element(offer, 'name', product_name)
                if common_desc:
                    create_xml_element(offer, 'description', common_desc)
                create_xml_element(offer, 'price', '0.00')  # Default price
                create_xml_element(offer, 'currencyId', 'UAH')
                
                # Add pictures
                for pic_url in common_pics:
                    if pic_url:
                        create_xml_element(offer, 'picture', pic_url)
                
                offer_count += 1
                continue
            
            for var in variants:
                var_data = var.get('data', {}) if isinstance(var.get('data'), dict) else {}
                var_attr = var_data.get('attributes', {}) or var.get('attributes', {})
                
                # Get SKU or use variant ID
                sku = var_attr.get('sku') or var_attr.get('article') or str(var.get('id', ''))
                if not sku:
                    logger.warning(f"No SKU found for variant {var.get('id')}")
                    continue
                
                # Check availability
                stock = var_attr.get('stock', 0)
                try:
                    stock = int(stock) if stock is not None else 0
                except (ValueError, TypeError):
                    stock = 0
                    
                available = 'true' if stock > 0 else 'false'
                
                # Create offer element
                offer = ET.SubElement(offers_elem, 'offer')
                offer.set('id', str(sku))
                offer.set('available', available)

                # Price
                price = var_attr.get('price', 0)
                try:
                    price = float(price) if price is not None else 0.0
                except (ValueError, TypeError):
                    price = 0.0
                create_xml_element(offer, 'price', f"{price:.2f}")
                
                # Stock
                create_xml_element(offer, 'stock', str(stock))

                # Name and description
                name = var_attr.get('name') or product_name
                create_xml_element(offer, 'name', name)
                
                desc = var_attr.get('description') or common_desc
                if desc:
                    create_xml_element(offer, 'description', desc)

                # Barcode
                barcode = var_attr.get('barcode')
                if barcode:
                    create_xml_element(offer, 'barcode', barcode)

                # Currency
                currency = var_attr.get('currency_code', 'UAH')
                create_xml_element(offer, 'currencyId', currency)
                
                # Purchase price
                purchase_price = var_attr.get('purchased_price')
                if purchase_price is not None:
                    try:
                        purchase_price = float(purchase_price)
                        create_xml_element(offer, 'purchase_price', f"{purchase_price:.2f}")
                    except (ValueError, TypeError):
                        pass

                # Unit and dimensions
                unit_type = var_attr.get('unit_type')
                if unit_type:
                    create_xml_element(offer, 'unit', unit_type)
                
                for dim in ('weight', 'length', 'width', 'height'):
                    dim_value = var_attr.get(dim)
                    if dim_value is not None:
                        create_xml_element(offer, dim, str(dim_value))

                # Category
                category_id = var_attr.get('category_id')
                if category_id:
                    create_xml_element(offer, 'categoryId', str(category_id))

                # Custom fields as parameters
                custom_fields = var_attr.get('custom_fields', [])
                if isinstance(custom_fields, list):
                    for cf in custom_fields:
                        if isinstance(cf, dict) and cf.get('uuid') and cf.get('value'):
                            param = ET.SubElement(offer, 'param')
                            param.set('name', str(cf['uuid']))
                            param.text = safe_text(cf['value'])

                # Pictures: variant-level or fallback to product-level
                pics = var_attr.get('pictures') or common_pics or []
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

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return Response("OK", status=200)

@app.errorhandler(404)
def not_found(error):
    return Response("Not Found", status=404)

@app.errorhandler(500)
def internal_error(error):
    return Response("Internal Server Error", status=500)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
