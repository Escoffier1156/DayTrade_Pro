import json
import urllib.request

TARGETS_FILE = "data/today_targets.json"

data = json.load(open(TARGETS_FILE))

# Keep only HIT_TP/HIT_SL (like Ibiden)
new_targets = [t for t in data.get("targets", []) if t.get("status") != "OPEN"]

closed_cost = sum(t.get("entry_price", 0) * t.get("shares", 0) for t in new_targets)
remaining = 10_000_000 - closed_cost
print(f"Closed cost: {closed_cost}, Remaining: {remaining}")

candidates = ["9984", "8035", "6857", "285A", "5803", "9983", "6762", "6920", "6954"]
accepted = []
base_cost = 0

import re
cookie = ""
with open("config/secrets.env") as f:
    m = re.search(r'KABUTAN_COOKIE=(.+)', f.read())
    if m: cookie = m.group(1).strip()

def fetch_price(code):
    req = urllib.request.Request(f"https://kabutan.jp/stock/?code={code}", headers={'User-Agent': 'Mozilla/5.0', 'Cookie': cookie})
    html = urllib.request.urlopen(req).read().decode('utf-8', 'replace')
    m = re.search(r'<span class="kabuka">([\d,.]+)円</span>', html)
    name = re.search(r'<h2><span class="name">([^<]+)</span>', html)
    return float(m.group(1).replace(',','')), name.group(1) if name else code

for code in candidates:
    if len(accepted) >= 4:
        break
    try:
        px, name = fetch_price(code)
        if base_cost + px * 100 <= remaining:
            base_cost += px * 100
            accepted.append({"code": code, "name": name, "price": px, "new_shares": 100})
            print(f"Accepted {name} ({code}) at {px}")
    except Exception as e:
        print(f"Failed to fetch {code}: {e}")

dyn_rem = remaining - base_cost
while dyn_rem > 0:
    cands = [r for r in accepted if r["price"] * 100 <= dyn_rem]
    if not cands: break
    best = min(cands, key=lambda r: r["price"] * r["new_shares"])
    best["new_shares"] += 100
    dyn_rem -= best["price"] * 100

for r in accepted:
    px = r["price"]
    shares = r.pop("new_shares")
    new_targets.append({
        "code": r["code"], "name": r["name"], "sector": "Unknown",
        "entry_price": px, "shares": shares, "stop": px * 0.98, "target": px * 1.015,
        "status": "OPEN", "latest_price": px, "history": []
    })

data["targets"] = new_targets
with open(TARGETS_FILE, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("Done replacing OPEN targets.")
