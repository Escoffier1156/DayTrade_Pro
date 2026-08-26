#!/usr/bin/env python3
"""
毎朝9:05に実行するスクリプト。
株探の「本日の活況銘柄」をスクレイピングし、
前日のデータ（universe_latest.json）と突き合わせて、
株価出来高50億以上、株数60万株以上の銘柄をピックアップする。
地合い（日経平均）に応じて3〜5銘柄に絞り、Slack通知を9:10に行う想定。
"""
import datetime as _dt
import gzip
import html as _html
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

# --- 設定値 ---
TARGET_URL = "https://kabutan.jp/warning/?mode=2_1&market=0&capitalization=-1&dispmode=normal&stc=&stm=0&page={page}"
MAX_PAGES = 5

MIN_AVG_VOLUME = 400_000        # 40万株
MIN_AVG_TURNOVER = 3_000_000_000 # 30億円

TP_PCT = 3.0 # 利確 +3%
SL_PCT = 2.0 # 損切り -2%

NIKKEI_STRONG = 0.5
NIKKEI_WEAK = -0.5

TOTAL_CAPITAL = 10_000_000
LOT = 100

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SECRETS_FILE = ROOT / "config" / "secrets.env"
UNIVERSE_FILE = DATA_DIR / "universe_latest.json"
TARGETS_FILE = DATA_DIR / "today_targets.json"

# 正規表現
_TABLE = re.compile(r'<table class="stock_table[^"]*">(.*?)</table>', re.S)
_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL = re.compile(r"<t[hd][^>]*>(.*?)</t[hd]>", re.S)

def load_env(name: str) -> str:
    v = os.environ.get(name)
    if v:
        return v
    if SECRETS_FILE.exists():
        for line in SECRETS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{name}=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip()
    return ""

def _text(s: str) -> str:
    return _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))).strip()

def _num(s: str) -> float | None:
    s = s.replace(",", "").replace("＋", "+").replace("−", "-").strip()
    if not s or s in {"-", "－", "—"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None

def fetch_page(url: str, cookie: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Cookie": cookie, "Accept-Encoding": "gzip"}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", "replace")

def parse_nikkei(doc: str) -> dict:
    # 日経平均を取得
    m = re.search(r'<table id="header_shisuu_big">(.*?)</table>', doc, re.S)
    if not m:
        return {}
    cells = [_text(c) for c in _CELL.findall(m.group(1))]
    nums = [c for c in cells if c and _num(c) is not None]
    if len(nums) >= 2:
        val = _num(nums[0])
        chg = _num(nums[1])
        if val and chg:
            pct = chg / (val - chg) * 100
            return {"value": val, "change": chg, "pct": pct}
    return {}

def parse_ranking(doc: str) -> list[dict]:
    m = _TABLE.search(doc)
    if not m:
        return []
    trs = _TR.findall(m.group(1))
    if not trs:
        return []
        
    header = [_text(c) for c in _CELL.findall(trs[0])]
    idx = {label: i for i, label in enumerate(header) if label}
    
    rows = []
    for tr in trs[1:]:
        c = [_text(x) for x in _CELL.findall(tr)]
        if len(c) < 4:
            continue
            
        pi = next((i for i, x in enumerate(c) if x.endswith("%")), None)
        if pi is None or pi < 3:
            continue
            
        pct = _num(c[pi].rstrip(" %"))
        chg = _num(c[pi - 1])
        price = None
        for j in range(pi - 2, 2, -1):
            v = _num(c[j])
            if v is not None:
                price = v
                break
                
        if price is not None:
            rows.append({
                "code": c[0],
                "name": c[1],
                "price": price,
                "change_pct": pct
            })
    return rows

def slack_post(text: str):
    token = load_env("SLACK_BOT_TOKEN")
    channel = load_env("SLACK_CHANNEL_ALERTS")
    if not token or not channel:
        print("Slack Token/Channelが設定されていません。標準出力のみ行います。")
        print("---")
        print(text)
        print("---")
        return
        
    data = json.dumps({"channel": channel, "text": text}, ensure_ascii=False).encode()
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage", data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        res = json.loads(r.read())
        if not res.get("ok"):
            print(f"Slack送信失敗: {res.get('error')}")

def main():
    cookie = load_env("KABUTAN_COOKIE")
    
    if not UNIVERSE_FILE.exists():
        print(f"エラー: {UNIVERSE_FILE} が見つかりません。先に fetch_yesterday.py を実行してください。")
        return
        
    universe = json.loads(UNIVERSE_FILE.read_text(encoding="utf-8"))
    
    print("株探から本日の活況銘柄をスクレイピング中...")
    all_rows = []
    nikkei = {}
    for page in range(1, MAX_PAGES + 1):
        url = TARGET_URL.format(page=page)
        try:
            doc = fetch_page(url, cookie)
            if page == 1:
                nikkei = parse_nikkei(doc)
            page_rows = parse_ranking(doc)
            all_rows.extend(page_rows)
            print(f"  Page {page}: {len(page_rows)} 銘柄取得")
        except Exception as e:
            print(f"  Page {page} 取得失敗: {e}")
            break
            
    if not nikkei:
        nikkei = {"pct": 0.0, "value": 0.0, "change": 0.0}
        print("日経平均が取得できませんでした。中立とみなします。")
        
    # 地合いによる銘柄数の決定
    n_pct = nikkei.get("pct", 0)
    if n_pct >= NIKKEI_STRONG:
        pick_count = 5
        regime = "強気"
    elif n_pct <= NIKKEI_WEAK:
        pick_count = 3
        regime = "弱気"
    else:
        pick_count = 4
        regime = "中立"
        
    print(f"\n日経平均: {n_pct:+.2f}% ({regime}) -> {pick_count} 銘柄ピックアップします")
    
    # フィルタリング (出来高・代金・Universe存在確認)
    filtered = []
    for r in all_rows:
        u = universe.get(r["code"])
        if not u:
            continue
            
        if u["avg_volume"] >= MIN_AVG_VOLUME and u["avg_turnover"] >= MIN_AVG_TURNOVER:
            r["avg_volume"] = u["avg_volume"]
            r["avg_turnover"] = u["avg_turnover"]
            r["sector"] = u["sector"]
            filtered.append(r)
            
    # 当日の上昇率が高い順に並べる（株探の元の並び順でも可だが明示的にソート）
    filtered.sort(key=lambda x: -(x["change_pct"] or -99))
    
    picked = filtered[:pick_count]
    
    targets = []
    lines = [
        f"【買い付け推奨】地合い: {regime} (日経 {n_pct:+.2f}%) -> {pick_count}銘柄厳選",
        f"条件: 出来高{MIN_AVG_VOLUME//10000}万株以上, 売買代金{MIN_AVG_TURNOVER//100000000}億円以上",
        ""
    ]
    
    capital_per_symbol = TOTAL_CAPITAL / pick_count
    
    for i, r in enumerate(picked, 1):
        px = r["price"]
        shares = int(capital_per_symbol // px // LOT) * LOT
        if shares == 0:
            continue
            
        stop_px = px * (1 - SL_PCT / 100)
        target_px = px * (1 + TP_PCT / 100)
        
        targets.append({
            "code": r["code"],
            "name": r["name"],
            "sector": r["sector"],
            "entry_price": px,
            "shares": shares,
            "stop": stop_px,
            "target": target_px,
            "status": "OPEN", # OPEN, HIT_TP, HIT_SL
            "latest_price": px
        })
        
        lines.append(f"{i}. {r['code']} {r['name']} ({r['sector']})")
        lines.append(f"   現在値: {px:,.1f}円 ({r['change_pct']:+.2f}%)")
        lines.append(f"   数量: {shares:,}株 (約 {px * shares / 10000:,.0f}万円)")
        lines.append(f"   利確目安(+{TP_PCT}%): {target_px:,.1f}円")
        lines.append(f"   損切目安({-SL_PCT}%): {stop_px:,.1f}円")
        lines.append(f"   (前日20日平均 - 代金: {r['avg_turnover']/100000000:,.1f}億円, 出来高: {r['avg_volume']/10000:,.0f}万株)")
        lines.append("")
        
    if not targets:
        lines.append("※ 本日の条件に合致する銘柄はありませんでした。")
        
    text = "\n".join(lines)
    
    # Target保存
    with open(TARGETS_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "date": _dt.date.today().isoformat(),
            "targets": targets
        }, f, ensure_ascii=False, indent=2)
        
    print("\n--- Slack 通知内容 ---")
    print(text)
    
    slack_post(text)
    print("\n処理完了。ターゲットを保存しました。")

if __name__ == "__main__":
    main()
