import requests
import json
import sys
sys.stdout.reconfigure(encoding='utf-8')

r = requests.get('http://127.0.0.1:8000/api/products/by-parent-sku/admin12')
data = r.json()
p = data.get('data', {})
print('code:', data.get('code'))
print('parent_sku:', p.get('parent_sku'))
print('brand:', p.get('brand'))
print('store_account:', p.get('store_account'))
print('color_options:', p.get('color_options'))
print('size_options:', p.get('size_options'))
print('variation count:', len(p.get('variations', [])))
print('package_length:', p.get('package_length'))
print('package_weight:', p.get('package_weight'))
print('item_length:', p.get('item_length'))
print('model_number:', p.get('model_number'))
print('model_name:', p.get('model_name'))
print('variation[0]:', json.dumps({
    'sku': p['variations'][0].get('sku'),
    'color': p['variations'][0].get('color'),
    'size': p['variations'][0].get('size'),
    'length_cm': p['variations'][0].get('length_cm'),
    'purchase_price': p['variations'][0].get('purchase_price'),
    'ean': p['variations'][0].get('ean'),
    'price_jpy': p['variations'][0].get('price_jpy'),
}, ensure_ascii=False) if p.get('variations') else 'none')
