import requests
import json

res = requests.get("http://127.0.0.1:8000/api/products/56")
data = res.json()
print("Product 56:", data["code"], data["msg"])
if data["code"] == 0:
    p = data["data"]
    print("Title:", p.get("title"))
    print("Variations count:", len(p.get("variations", [])))
    for v in p.get("variations", []):
        print("  Var:", v.get("sku"), v.get("length_cm"), v.get("width_cm"), v.get("height_cm"), v.get("weight_kg"), v.get("shipping_channel"))
