import json, re, time, html as ihtml, requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}
S = requests.Session()
S.headers.update(HEADERS)


def to_float(v):
    s = str(v).replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        x = float(s)
        return x if x > 0 else None
    except ValueError:
        return None


def collect(o, out):
    """Zbiera (cena, czy_dostepne) ze wszystkich ofert w JSON-LD."""
    if isinstance(o, dict):
        p = o.get("price", o.get("lowPrice"))
        if p is not None:
            f = to_float(p)
            if f:
                out.append((f, "OutOfStock" not in str(o.get("availability", ""))))
        for v in o.values():
            collect(v, out)
    elif isinstance(o, list):
        for v in o:
            collect(v, out)


def meta(page, prop):
    for pat in (
        rf'<meta[^>]+(?:property|name)="{prop}"[^>]+content="([^"]+)"',
        rf'<meta[^>]+content="([^"]+)"[^>]+(?:property|name)="{prop}"',
    ):
        m = re.search(pat, page)
        if m:
            return ihtml.unescape(m.group(1))
    return None


def price_from_html(page):
    found = []
    for m in re.finditer(r'<script[^>]*ld\+json[^>]*>(.*?)</script>', page, re.S):
        try:
            collect(json.loads(m.group(1)), found)
        except Exception:
            continue
    if found:
        in_stock = [p for p, ok in found if ok]
        return min(in_stock or [p for p, _ in found]), "JSON-LD"
    for prop in ("product:price:amount", "og:price:amount"):
        v = meta(page, prop)
        if v and to_float(v):
            return to_float(v), prop
    m = re.search(r'"price"\s*:\s*"?([\d.,]+)"?', page)
    if m and to_float(m.group(1)):
        return to_float(m.group(1)), "regex"
    return None, None


def price_from_text(text):
    """Zapasowa metoda: czyta cenę z tekstowej wersji strony."""
    m = re.search(r'Aktualna cena\s*([\d\s\u00a0]+[.,]\d{2})\s*zł', text)
    if not m:
        i = text.find("**Kolor:**")
        seg = text[i:i + 300] if i >= 0 else text[:3000]
        m = re.search(r'(\d[\d\s\u00a0]*[.,]\d{2})\s*zł', seg)
    return to_float(m.group(1)) if m else None


def fetch(url):
    """Zwraca (tekst, rodzaj) albo (None, powód)."""
    status = "brak odpowiedzi"
    for _ in range(2):
        try:
            r = S.get(url, timeout=25)
            if r.ok:
                return r.text, "html"
            status = f"HTTP {r.status_code}"
        except Exception as e:
            status = type(e).__name__
        time.sleep(2)
    return None, status


def fetch_text_fallback(url):
    try:
        r = requests.get("https://r.jina.ai/" + url, timeout=45,
                         headers={"Accept": "text/plain"})
        if r.ok:
            return r.text
    except Exception:
        pass
    return None


def main():
    with open("products.json", encoding="utf-8") as f:
        products = json.load(f)

    for p in products:
        for o in p["offers"]:
            url, label = o["url"], f'{o.get("shop", "?")} | {p.get("name", "")[:40]}'
            page, kind = fetch(url)
            price = method = None

            if page:
                price, method = price_from_html(page)
                if not p.get("image"):
                    img = meta(page, "og:image")
                    if img:
                        p["image"] = img
                if not p.get("name"):
                    title = meta(page, "og:title")
                    if title:
                        p["name"] = title.split(" | ")[0].strip()

            if price is None:
                text = fetch_text_fallback(url)
                if text:
                    price, method = price_from_text(text), "tekst (zapas)"
                    if not p.get("image"):
                        for im in re.findall(r'!\[[^\]]*\]\((https?://\S+?\.(?:jpg|jpeg|png|webp))\)', text):
                            if "product" in im:
                                p["image"] = im
                                break
                    if not p.get("name"):
                        t = re.search(r'^Title:\s*(.+)$', text, re.M)
                        if t:
                            p["name"] = t.group(1).split(" | ")[0].strip()

            if price:
                o["price"] = price
                print(f"OK    {label} -> {price:.2f} zł ({method})")
            else:
                print(f"BRAK  {label} -> nie znaleziono ceny ({kind})")
            time.sleep(1)

    with open("products.json", "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
