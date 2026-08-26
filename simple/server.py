#!/usr/bin/env python3
"""
超シンプルなWebサーバー
web/dist/ にあるビルド済みのフロントエンドを静的配信しつつ、
/api/targets というAPIエンドポイントで data/today_targets.json の内容を返す。
"""
import http.server
import socketserver
import json
import urllib.parse
from pathlib import Path

PORT = 8787
ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT / "web" / "dist"
TARGETS_FILE = ROOT / "data" / "today_targets.json"
HISTORY_FILE = ROOT / "data" / "trade_history.json"
WEB_TOKEN = "l5cL0jRp9Yzcj_dRutcc43zNmZG0oOFb"

class SimpleAPIHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST_DIR), **kwargs)

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
            # CORS許可 (開発用)
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
            # CORS許可 (開発用)
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
        
        # それ以外は web/dist/ 以下の静的ファイルを返す
        super().do_GET()

class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

def main():
    if not DIST_DIR.exists():
        print(f"警告: {DIST_DIR} が存在しません。先に npm run build を実行してください。")
        
    with ReusableTCPServer(("", PORT), SimpleAPIHandler) as httpd:
        print(f"DayTrade Pro Dashboard Server started at http://localhost:{PORT}")
        print(f"Serving static files from {DIST_DIR}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server...")

if __name__ == "__main__":
    main()
