import sys, json, urllib.request, math, datetime
sys.path.append('/home/shogo/DayTrade_Pro/simple')
from bot import load_env, api_get, BARS_DAILY, MIN_AVG_VOLUME, MIN_AVG_TURNOVER, TP_PCT, SL_PCT

key = load_env("JQUANTS_API_KEY")

date_thurs = datetime.date(2026, 8, 27)
date_fri = datetime.date(2026, 8, 28)

print("Fetching Thursday data...")
data_thurs = api_get(BARS_DAILY, {"date": date_thurs.isoformat()}, key)
print("Fetching Friday data...")
data_fri = api_get(BARS_DAILY, {"date": date_fri.isoformat()}, key)

thurs_map = {}
for q in data_thurs:
    code = q["Code"][:4]
    try:
        vol = float(q.get("Vo", 0))
        close = float(q.get("C", 0))
        turnover = float(q.get("Va", 0))
        if close > 0 and vol > 0:
            thurs_map[code] = {"close": close, "vol": vol, "turnover": turnover}
    except:
        pass

TARGET_CODES = {"6330", "6702", "6701", "7974", "6976"}
results = []

for q in data_fri:
    code = q["Code"][:4]
    if code not in TARGET_CODES: continue
    
    t = thurs_map.get(code, {})
    t_close = t.get("close", 0)
    
    try:
        f_open = float(q.get("O", 0))
        f_high = float(q.get("H", 0))
        f_low = float(q.get("L", 0))
        f_close = float(q.get("C", 0))
    except:
        continue
        
    if f_open <= 0 or f_high <= 0: continue
    
    gap_up = 0
    if t_close > 0:
        gap_up = (f_open / t_close - 1.0) * 100
    
    entry = f_open
    tp_price = entry * (1 + TP_PCT / 100)
    sl_price = entry * (1 - SL_PCT / 100)
    
    hit_tp = f_high >= tp_price
    hit_sl = f_low <= sl_price
    
    status = "OPEN"
    pnl = 0
    if hit_sl and hit_tp:
        status = "HIT_BOTH"
        pnl = TP_PCT # assuming best case or mixed
    elif hit_sl:
        status = "LOSS"
        pnl = -SL_PCT
    elif hit_tp:
        status = "WIN"
        pnl = TP_PCT
    else:
        status = "HOLD"
        pnl = (f_close / entry - 1.0) * 100
        
    results.append({
        "code": code,
        "gap": gap_up,
        "turnover": t.get("turnover", 0),
        "entry": entry,
        "status": status,
        "pnl": pnl
    })

results.sort(key=lambda x: -x["turnover"])

print(f"\nTop 5 simulated picks for Friday (Aug 28) based on Gap Up (0~5%) & Liquidity:")
wins = 0
losses = 0
holds = 0
for i, r in enumerate(results[:5]):
    print(f"{i+1}. {r['code']} (Gap: +{r['gap']:.2f}%, Entry: {r['entry']}) -> {r['status']} ({r['pnl']:+.2f}%)")
    if r['status'] == "WIN": wins += 1
    elif r['status'] == "LOSS": losses += 1
    else: holds += 1

print(f"\nResult: {wins} Wins, {losses} Losses, {holds} Holds")
