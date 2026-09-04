#!/usr/bin/env python3
"""
Super simple web server.
Serves the built frontend statically from web/dist/,
and exposes the /api/targets endpoint to return the contents of data/today_targets.json.
"""
import http.server
import socketserver
import json
import urllib.parse
import urllib.request
import re
import subprocess
import datetime
from pathlib import Path

PORT = 8787
ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT / "web" / "dist"
TARGETS_FILE = ROOT / "data" / "today_targets.json"
HISTORY_FILE = ROOT / "data" / "trade_history.json"

def record_trade(code: str, name: str, side: str, qty: int, price: float, pnl: float):
    trade = {"date": datetime.date.today().isoformat(), "time": datetime.datetime.now().strftime("%H:%M:%S"), "ticker": code, "name": name, "side": side, "qty": qty, "price": price, "pnl": pnl}
    history = []
    if HISTORY_FILE.exists():
        try: history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError: pass
    history.append(trade)
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

WEB_TOKEN = "l5cL0jRp9Yzcj_dRutcc43zNmZG0oOFb"

class SimpleAPIHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST_DIR), **kwargs)

    def send_custom_error(self, code, message):
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(message.encode('utf-8'))

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        
        if parsed.path == "/api/targets":
            if qs.get("k", [""])[0] != WEB_TOKEN:
                self.send_error(403, "Forbidden")
                return
                
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            # Allow CORS (for development)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            
            try:
                if TARGETS_FILE.exists():
                    data = TARGETS_FILE.read_bytes()
                else:
                    data = json.dumps({"date": "None", "targets": []}).encode("utf-8")
                self.wfile.write(data)
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        if parsed.path == "/api/history":
            if qs.get("k", [""])[0] != WEB_TOKEN:
                self.send_error(403, "Forbidden")
                return
                
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            # Allow CORS (for development)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            
            try:
                if HISTORY_FILE.exists():
                    self.wfile.write(HISTORY_FILE.read_bytes())
                else:
                    self.wfile.write(b"[]")
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return
        if parsed.path == "/api/preview_report":
            if qs.get("k", [""])[0] != WEB_TOKEN:
                self.send_error(403, "Forbidden")
                return
                
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            
            try:
                import datetime
                target_date = datetime.date.today().isoformat()
                lines = [f"【本日の運用成績レポート】 ({target_date})", "---"]
                total_realized_pnl = 0
                total_unrealized_pnl = 0
                
                history_data = []
                if HISTORY_FILE.exists():
                    try:
                        all_history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
                        history_data = [h for h in all_history if h.get("date") == target_date]
                    except Exception:
                        pass
                
                lines.append("■ 決済済 (実現損益)")
                if not history_data:
                    lines.append("本日の決済済み銘柄はありません。")
                else:
                    for i, h in enumerate(history_data, 1):
                        side_str = str(h.get("side", ""))
                        if "TP" in side_str:
                            result = "利確"
                        elif "SL" in side_str:
                            result = "損切"
                        elif "PARTIAL" in side_str:
                            result = "部分決済"
                        else:
                            result = side_str
                        pnl = float(h.get("pnl", 0))
                        total_realized_pnl += pnl
                        lines.extend([
                            f"{i}. {h.get('time', '')} {h.get('ticker', '')} {h.get('name', '')} - {result}",
                            f"   数量: {h.get('qty', 0):,}株 / 決済値: {h.get('price', 0):,.1f}円",
                            f"   損益: {pnl:+,.0f}円"
                        ])
                
                lines.append("")
                lines.append("■ 保有中 (含み損益)")
                
                targets_data = []
                if TARGETS_FILE.exists():
                    try:
                        tdata = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
                        if tdata.get("date") == target_date:
                            targets_data = tdata.get("targets", [])
                    except Exception:
                        pass
                
                open_targets = [t for t in targets_data if t.get("status") == "OPEN"]
                
                if not open_targets:
                    lines.append("現在保有中の銘柄はありません。")
                else:
                    for i, t in enumerate(open_targets, 1):
                        code, name, entry, shares = t.get("code"), t.get("name"), float(t.get("entry_price", 0)), int(t.get("shares", 0))
                        current_px = float(t.get("latest_price", entry))
                        pnl = (current_px - entry) * shares
                        total_unrealized_pnl += pnl
                        lines.extend([
                            f"{i}. {code} {name}",
                            f"   数量: {shares:,}株 / エントリー: {entry:,.1f}円 -> 現在値: {current_px:,.1f}円",
                            f"   含み損益: {pnl:+,.0f}円"
                        ])
                
                lines.append("---")
                lines.append("【本日の合計】")
                lines.append(f"実現損益: {total_realized_pnl:+,.0f}円")
                lines.append(f"含み損益: {total_unrealized_pnl:+,.0f}円")
                
                text = "\n".join(lines)
                    
                self.wfile.write(json.dumps({"text": text}).encode("utf-8"))
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return
            
        # Serve static files under web/dist/ but add no-cache headers for html
        path = self.translate_path(self.path)
        if path.endswith(".html") or self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            index_path = DIST_DIR / "index.html"
            if index_path.exists():
                self.wfile.write(index_path.read_bytes())
            return
            
        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        
        if parsed.path == "/api/add_target":
            if qs.get("k", [""])[0] != WEB_TOKEN:
                self.send_custom_error(403, "Forbidden")
                return
            
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            try:
                payload = json.loads(post_data.decode('utf-8'))
                code = payload.get("code")
                if not code:
                    self.send_custom_error(400, "Bad Request: code missing")
                    return
                
                
                cookie = ""
                secrets_path = ROOT / "config" / "secrets.env"
                if secrets_path.exists():
                    m = re.search(r'KABUTAN_COOKIE=(.+)', secrets_path.read_text(encoding="utf-8"))
                    if m: cookie = m.group(1).strip()
                    
                url = f"https://kabutan.jp/stock/?code={code}"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Cookie': f"kabutan={cookie}" if cookie else ""})
                
                try:
                    html = urllib.request.urlopen(req).read().decode('utf-8')
                    m = re.search(r'<span class=\"kabuka\">([\d,.]+)円</span>', html)
                    m_name = re.search(r'<title>(.*?)【', html)
                    m_sector = re.search(r'<a href=\"/category/\?industry=.*?\">(.*?)</a>', html)
                    
                    if not m:
                        self.send_custom_error(404, "Stock not found on Kabutan")
                        return
                        
                    px = float(m.group(1).replace(',',''))
                    name = m_name.group(1).strip() if m_name else "Unknown"
                    sector = m_sector.group(1).strip() if m_sector else "Unknown"
                    
                    TP_PCT = 1.5
                    SL_PCT = 2.0
                    subprocess.run(["systemctl", "--user", "stop", "daytrade-monitor"])
                    
                    data = {"targets": []}
                    if TARGETS_FILE.exists():
                        data = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
                        
                    # Avoid duplicates
                    for t in data.get("targets", []):
                        if t.get("code") == code and t.get("status") == "OPEN":
                            subprocess.run(["systemctl", "--user", "start", "daytrade-monitor"])
                            self.send_custom_error(400, "Stock already in OPEN targets")
                            return
                            
                    open_targets = [t for t in data.get("targets", []) if t.get("status") == "OPEN"]
                    
                    target_px = px * (1 + TP_PCT / 100)
                    stop_px = px * (1 - SL_PCT / 100)
                    
                    new_target = {
                        "code": code,
                        "name": name,
                        "sector": sector,
                        "entry_price": px,
                        "shares": 0,
                        "stop": stop_px,
                        "target": target_px,
                        "status": "OPEN",
                        "latest_price": px,
                        "history": []
                    }
                    
                    all_targets = open_targets + [new_target]
                    
                    closed_cost = sum(t.get("entry_price", 0) * t.get("shares", 0) for t in data.get("targets", []) if t.get("status") != "OPEN")
                    
                    # 1. Base allocation of 100 shares
                    base_cost = closed_cost
                    for t in all_targets:
                        current_px = t.get("latest_price", t.get("entry_price"))
                        base_cost += current_px * 100
                        t["new_shares"] = 100
                        
                    if base_cost > 10_000_000:
                        subprocess.run(["systemctl", "--user", "start", "daytrade-monitor"])
                        self.send_custom_error(400, f"本日の残余資金枠が足りません（決済済み銘柄も拘束されます）。他の銘柄を削除して枠を空けてください。")
                        return
                        
                    # 2. Distribute remaining capital
                    remaining = 10_000_000 - base_cost
                    while remaining > 0:
                        candidates = []
                        for t in all_targets:
                            current_px = t.get("latest_price", t.get("entry_price"))
                            if current_px * 100 <= remaining:
                                candidates.append(t)
                        if not candidates:
                            break
                            
                        best = min(candidates, key=lambda t: t.get("latest_price", t.get("entry_price")) * t["new_shares"])
                        current_px = best.get("latest_price", best.get("entry_price"))
                        best["new_shares"] += 100
                        remaining -= current_px * 100
                        
                    # 3. Apply rebalancing to existing targets
                    for t in open_targets:
                        if t["new_shares"] < t["shares"]:
                            shares_to_sell = t["shares"] - t["new_shares"]
                            current_px = t.get("latest_price", t.get("entry_price"))
                            pnl = (current_px - t["entry_price"]) * shares_to_sell
                            record_trade(t["code"], t["name"], "SELL(REBALANCE)", shares_to_sell, current_px, pnl)
                        t["shares"] = t.pop("new_shares")
                        
                    # 4. Finalize new target
                    new_target["shares"] = new_target.pop("new_shares")
                    data.setdefault("targets", []).append(new_target)
                    TARGETS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                    
                    subprocess.run(["systemctl", "--user", "start", "daytrade-monitor"])
                    
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "success", "added": new_target}, ensure_ascii=False).encode('utf-8'))
                    return
                except Exception as e:
                    self.send_custom_error(500, f"Scrape Error: {str(e)}")
                    return
            except Exception as e:
                self.send_custom_error(500, f"Internal Error: {str(e)}")
                return

        if parsed.path == "/api/action":
            if qs.get("k", [""])[0] != WEB_TOKEN:
                self.send_error(403, "Forbidden")
                return
            
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            try:
                payload = json.loads(post_data.decode('utf-8'))
                ticker = payload.get("ticker")
                action = payload.get("action")
                
                if not ticker or action not in ["TP", "SL", "CANCEL_TP", "REMOVE"]:
                    self.send_error(400, "Bad Request")
                    return
                    
                if TARGETS_FILE.exists():
                    if action == "REMOVE":
                        subprocess.run(["systemctl", "--user", "stop", "daytrade-monitor"])
                        data = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
                        original_len = len(data.get("targets", []))
                        data["targets"] = [t for t in data.get("targets", []) if t["code"] != str(ticker)]
                        if len(data["targets"]) < original_len:
                            TARGETS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                        subprocess.run(["systemctl", "--user", "start", "daytrade-monitor"])
                    else:
                        data = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
                        updated = False
                        for t in data.get("targets", []):
                            if t["code"] == str(ticker):
                                # Allow CANCEL_TP even if status is not OPEN
                                if action == "CANCEL_TP" or t["status"] == "OPEN":
                                    t["manual_action"] = action
                                    updated = True
                                    break
                                
                        if updated:
                            TARGETS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                        
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success"}).encode("utf-8"))
            except Exception as e:
                self.send_error(500, f"Internal Server Error: {e}")
            return
            
        if parsed.path == "/api/report":
            if qs.get("k", [""])[0] != WEB_TOKEN:
                self.send_error(403, "Forbidden")
                return
            
            try:
                state_file = ROOT / "data" / "bot_state.json"
                if state_file.exists():
                    state = json.loads(state_file.read_text(encoding="utf-8"))
                else:
                    state = {}
                state["trigger_report"] = True
                state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success"}).encode("utf-8"))
            except Exception as e:
                self.send_error(500, f"Internal Server Error: {e}")
            return
            
        self.send_error(404, "Not Found")

class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

def main():
    if not DIST_DIR.exists():
        print(f"Warning: {DIST_DIR} does not exist. Please run 'npm run build' first.")
        
    with ReusableTCPServer(("", PORT), SimpleAPIHandler) as httpd:
        print(f"DayTrade Pro Dashboard Server started at http://localhost:{PORT}")
        print(f"Serving static files from {DIST_DIR}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server...")

if __name__ == "__main__":
    main()
