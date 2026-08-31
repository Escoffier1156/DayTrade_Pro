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
                
                if not ticker or action not in ["TP", "SL"]:
                    self.send_error(400, "Bad Request")
                    return
                    
                if TARGETS_FILE.exists():
                    data = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
                    updated = False
                    for t in data.get("targets", []):
                        if t["code"] == str(ticker) and t["status"] == "OPEN":
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
