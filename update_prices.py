import json, re, requests

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

def find_price(o):
    if isinstance(o, dict):
        for k in ("price", "lowPrice"):
            if k in o:
                try:
                    return float(str(o[k]).replace(",", "."))
                except ValueError:
                    pass
        for v in o.values():
            r = find_price(v)
            if r:
                return r
    elif isinstance(o, list):
        for v in o:
            r = find_price(v)
            if r:
                return r
    return None

def get_price(url):
    try:
        html = requests.get(url, headers=H, timeout=20).text
    except Exception:
        return None
    for m in re.finditer(r'<script[^>]*ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        p = find_price(data)
        if p:
            return p
    m = re.search(r'product:price:amount"\s+content="([\d.,]+)"', html)
    if m:
        return float(m.group(1).replace(",", "."))
    return None

with open("products.json", encoding="utf-8") as f:
    products = json.load(f)

for p in products:
    for o in p["offers"]:
        price = get_price(o["url"])
        if price:          # jeśli się nie udało, zostaje stara cena
            o["price"] = price

with open("products.json", "w", encoding="utf-8") as f:
    json.dump(products, f, ensure_ascii=False, indent=2)
