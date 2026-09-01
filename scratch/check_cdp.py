import urllib.request
import json

try:
    with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=2) as resp:
        print("CDP reachable:", json.loads(resp.read().decode()))
except Exception as e:
    print("CDP not reachable on 9222:", e)
