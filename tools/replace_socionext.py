import json
import datetime
import urllib.request, re

TARGETS_FILE = 'data/today_targets.json'
HISTORY_FILE = 'data/trade_history.json'

with open(TARGETS_FILE, 'r', encoding='utf-8') as f:
    data = json.load(f)

targets = data.get('targets', [])

# Find and remove Socionext (6526)
socionext = None
for i, t in enumerate(targets):
    if t['code'] == '6526':
        socionext = targets.pop(i)
        break

if not socionext:
    print("Socionext not found in targets!")
    exit(1)

# Sell Socionext
sell_price = socionext.get('latest_price', socionext['entry_price'])
shares = socionext['shares']
pnl = (sell_price - socionext['entry_price']) * shares
sell_value = sell_price * shares

history_entry = {
    "date": datetime.date.today().isoformat(),
    "time": datetime.datetime.now().strftime("%H:%M:%S"),
    "ticker": "6526",
    "name": "ソシオネクス",
    "side": "MANUAL_REPLACE",
    "price": sell_price,
    "qty": shares,
    "pnl": pnl
}

try:
    with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
        history = json.load(f)
except Exception:
    history = []

history.append(history_entry)

with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
    json.dump(history, f, ensure_ascii=False, indent=2)

print(f"Sold Socionext: {shares} shares @ {sell_price}, PNL: {pnl}")

# Add Itochu (8001)
itochu_price = 2194.5
itochu_shares = int(sell_value // itochu_price // 100) * 100
if itochu_shares == 0:
    itochu_shares = 100

itochu = {
    "code": "8001",
    "name": "伊藤忠",
    "sector": "卸売業",
    "entry_price": itochu_price,
    "shares": itochu_shares,
    "stop": itochu_price * 0.98,
    "target": itochu_price * 1.025,
    "status": "OPEN",
    "latest_price": itochu_price,
    "history": []
}

targets.append(itochu)

with open(TARGETS_FILE, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"Added Itochu: {itochu_shares} shares @ {itochu_price}")
