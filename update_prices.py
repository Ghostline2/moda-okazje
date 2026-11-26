import json, os, re, time, datetime, html as ihtml, requests

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
    for pat, name in (
        (r'itemprop="price"[^>]*content="([\d.,]+)"', "itemprop"),
        (r'content="([\d.,]+)"[^>]*itemprop="price"', "itemprop"),
        (r'"(?:price|salePrice|finalPrice|currentPrice|priceGross|special_price)"\s*:\s*"?([\d]+(?:[.,]\d+)?)"?', "json"),
        (r'data-price="([\d.,]+)"', "data-price"),
        (r'class="[^"]*(?:price|cena)[^"]*"[^>]*>\s*(?:<[^>]+>\s*)*([\d\s\u00a0]+[.,]\d{2})\s*(?:zł|PLN)?', "html-cena"),
    ):
        m = re.search(pat, page, re.I)
        if m and to_float(m.group(1)):
            return to_float(m.group(1)), name
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
    for attempt in range(2):
        try:
            r = S.get(url, timeout=(8, 15))
            if r.ok:
                return r.text, "html"
            status = f"HTTP {r.status_code}"
        except Exception as e:
            status = type(e).__name__
            if "Timeout" in status:
                break  # sklep nie odpowiada, nie ma sensu czekać drugi raz
        time.sleep(2)
    return None, status


def fetch_text_fallback(url):
    try:
        r = requests.get("https://r.jina.ai/" + url, timeout=30,
                         headers={"Accept": "text/plain"})
        if r.ok:
            return r.text
    except Exception:
        pass
    return None


TODAY = datetime.date.today().isoformat()


def notify(text):
    """Wysyła alert na Telegram (tylko jeśli ustawiono sekrety TELEGRAM_TOKEN i TELEGRAM_CHAT_ID)."""
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat, "text": text}, timeout=15)
    except Exception:
        pass


def main():
    with open("products.json", encoding="utf-8") as f:
        products = json.load(f)
    try:
        with open("history.json", encoding="utf-8") as f:
            history = json.load(f)
    except Exception:
        history = {}

    for p in products:
        for o in p["offers"]:
            url = o["url"]
            page, kind = fetch(url)
            price = method = None
            fb = ""

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
                if not text:
                    fb = "zapas: brak odpowiedzi"
                else:
                    price = price_from_text(text)
                    method = "tekst (zapas)"
                    if price is None:
                        fb = "zapas: brak ceny w tekście"
                    if not p.get("image"):
                        for im in re.findall(r'!\[[^\]]*\]\((https?://\S+?\.(?:jpg|jpeg|png|webp))\)', text):
                            if "product" in im:
                                p["image"] = im
                                break
                    if not p.get("name"):
                        t = re.search(r'^Title:\s*(.+)$', text, re.M)
                        if t:
                            p["name"] = t.group(1).split(" | ")[0].strip()

            label = f'{o.get("shop", "?")} | {p.get("name", "")[:40]}'
            if price:
                old = o.get("price")
                o["price"] = price
                h = history.setdefault(url, {})
                h[TODAY] = price
                for d in sorted(h)[:-45]:
                    del h[d]
                if old and price <= old * 0.9:
                    pct = round((old - price) / old * 100)
                    notify(f"🔻 -{pct}%  {p.get('name', '')}\n{old:.2f} → {price:.2f} zł ({o.get('shop', '')})\n{o.get('aff') or url}")
                print(f"OK    {label} -> {price:.2f} zł ({method})")
            else:
                print(f"BRAK  {label} -> nie znaleziono ceny (strona: {kind}; {fb})")
            time.sleep(1)

    with open("products.json", "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)
    with open("history.json", "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=1, sort_keys=True)


if __name__ == "__main__":
    main()
