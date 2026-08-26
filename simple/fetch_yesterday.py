#!/usr/bin/env python3
"""
前日のデータ（直近20営業日分の平均出来高・平均売買代金）をJ-Quants APIから取得し、
data/universe_latest.json に保存するスクリプト。
"""
import datetime as _dt
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

API_BASE = "https://api.jquants.com/v2"
BARS_DAILY = "/equities/bars/daily"
CALENDAR = "/markets/calendar"
MASTER = "/equities/master"

AVG_WINDOW = 20
HTTP_TIMEOUT_SEC = 30
REQUEST_SLEEP_SEC = 0.3

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SECRETS_FILE = ROOT / "config" / "secrets.env"

def load_env(name: str) -> str:
    v = os.environ.get(name)
    if v:
        return v
    if SECRETS_FILE.exists():
        for line in SECRETS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{name}=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip()
    raise RuntimeError(f"{name} が設定されていません")

def api_get(path: str, params: dict, key: str) -> list[dict]:
    rows = []
    page = None
    while True:
        q = dict(params)
        if page:
            q["pagination_key"] = page
        url = f"{API_BASE}{path}?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers={"x-api-key": key})
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as r:
                doc = json.loads(r.read())
        except Exception as exc:
            raise RuntimeError(f"{path} 取得失敗: {exc}") from exc
        rows.extend(doc.get("data") or [])
        page = doc.get("pagination_key")
        time.sleep(REQUEST_SLEEP_SEC)
        if not page:
            return rows

def trading_days(key: str, end: _dt.date, count: int) -> list[_dt.date]:
    start = end - _dt.timedelta(days=count * 3)
    rows = api_get(CALENDAR, {"from": start.isoformat(), "to": end.isoformat()}, key)
    days = sorted(
        _dt.date.fromisoformat(r["Date"])
        for r in rows
        if str(r.get("HolDiv")) in {"1", "2"}
        and _dt.date.fromisoformat(r["Date"]) <= end
    )
    if not days:
        raise RuntimeError(f"{start}〜{end} に営業日がありません")
    return days[-count:]

def fetch_master(key: str, date: _dt.date) -> dict:
    rows = api_get(MASTER, {"date": date.isoformat()}, key)
    return {r["Code"]: r for r in rows}

def main():
    key = load_env("JQUANTS_API_KEY")
    today = _dt.date.today()
    
    # 20営業日 + バッファ5日分を取得
    days = trading_days(key, today, AVG_WINDOW + 5)
    
    # 最新の営業日（前日以前）
    target_day = None
    for d in reversed(days):
        if d < today:
            target_day = d
            break
            
    if not target_day:
        print("有効な過去の営業日が見つかりません。")
        return

    # 直近AVG_WINDOW日のデータを取得
    target_days = [d for d in days if d <= target_day][-AVG_WINDOW:]
    
    print(f"J-Quants APIから過去 {AVG_WINDOW} 営業日分のデータを取得中...")
    print(f"期間: {target_days[0]} 〜 {target_days[-1]}")
    
    by_symbol = {}
    for d in target_days:
        rows = api_get(BARS_DAILY, {"date": d.isoformat()}, key)
        for r in rows:
            by_symbol.setdefault(r["Code"], []).append(r)
        print(f"  {d}: {len(rows)} 銘柄取得")
        
    master = fetch_master(key, target_days[-1])
    
    universe = {}
    for code, bars in by_symbol.items():
        if len(bars) < AVG_WINDOW // 2:
            continue
            
        m = master.get(code)
        if not m or str(m.get("Mkt")) != "0111": # 東証プライムのみ
            continue
            
        total_vo = 0
        total_va = 0
        valid_bars = 0
        for b in bars:
            vo = b.get("Vo")
            va = b.get("Va")
            if vo is not None and va is not None:
                total_vo += float(vo)
                total_va += float(va)
                valid_bars += 1
                
        if valid_bars > 0:
            avg_vo = total_vo / valid_bars
            avg_va = total_va / valid_bars
            
            c4 = code[:-1] if code.endswith("0") and len(code) == 5 else code
            universe[c4] = {
                "code": c4,
                "name": m.get("CoName", ""),
                "sector": m.get("S33Nm", ""),
                "avg_volume": avg_vo,
                "avg_turnover": avg_va,
                "latest_close": float(bars[-1].get("C", 0))
            }
            
    print(f"母集団作成完了: {len(universe)} 銘柄")
    
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / "universe_latest.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(universe, f, ensure_ascii=False, indent=2)
    print(f"保存しました: {out_path}")

if __name__ == "__main__":
    main()
