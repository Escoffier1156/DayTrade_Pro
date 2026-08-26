#!/usr/bin/env python3
"""
統合マスターBot (bot.py)
J-Quantsデータ取得から、スクリーニング、日中の監視、そして大引け後のレポートまで、
すべてを時間に応じて自律的に実行するデーモンスクリプト。
"""
import time
import datetime as _dt
import sys
from pathlib import Path

# simple フォルダの各モジュールをインポート
import fetch_yesterday
import morning_screener
import intraday_monitor
import daily_report

def main():
    print("=== DayTrade Pro Master Bot Started ===")
    print("Bot is now running continuously and waiting for scheduled tasks...")
    
    # 状態管理フラグ（同じ日に複数回実行しないため）
    last_run_fetch = None
    last_run_screener = None
    last_run_report = None
    
    iteration_count = 0
    is_monitoring = False
    
    while True:
        try:
            now = _dt.datetime.now()
            today_str = now.date().isoformat()
            
            # --- 23:00 : fetch_yesterday.py ---
            if now.hour == 23 and now.minute >= 0 and last_run_fetch != today_str:
                print(f"[{now.strftime('%H:%M:%S')}] 実行: fetch_yesterday.main()")
                try:
                    fetch_yesterday.main()
                except Exception as e:
                    print(f"fetch_yesterday エラー: {e}")
                last_run_fetch = today_str
                
            # --- 09:10 : morning_screener.py ---
            if now.hour == 9 and now.minute >= 10 and now.minute < 30 and last_run_screener != today_str:
                print(f"[{now.strftime('%H:%M:%S')}] 実行: morning_screener.main()")
                try:
                    morning_screener.main()
                except Exception as e:
                    print(f"morning_screener エラー: {e}")
                last_run_screener = today_str
                
            # --- 08:55 ~ 11:30, 12:30 ~ 15:30 : intraday_monitor ---
            time_hm = now.hour * 100 + now.minute
            if (855 <= time_hm < 1130) or (1230 <= time_hm <= 1530):
                if not is_monitoring:
                    print(f"[{now.strftime('%H:%M:%S')}] --- 監視モード開始 ---")
                    is_monitoring = True
                    iteration_count = 0
                
                # 監視ステップを1回実行
                intraday_monitor.monitor_step(iteration_count)
                iteration_count += 1
                
                # 次の監視まで15秒待機
                # (API負荷軽減のため確実にスリープ)
                time.sleep(15)
                continue  # 1秒ごとのループではなく、監視中は15秒ペースで回す
            else:
                if is_monitoring:
                    print(f"[{now.strftime('%H:%M:%S')}] --- 監視モード終了 ---")
                    is_monitoring = False
            
            # --- 15:40 : daily_report.py ---
            if now.hour == 15 and now.minute >= 40 and last_run_report != today_str:
                print(f"[{now.strftime('%H:%M:%S')}] 実行: daily_report.main()")
                try:
                    daily_report.main()
                except Exception as e:
                    print(f"daily_report エラー: {e}")
                last_run_report = today_str
                
            # 監視時間外は1秒ごとにチェック（CPU負荷ゼロ）
            time.sleep(1)
            
        except KeyboardInterrupt:
            print("Bot stopped manually.")
            sys.exit(0)
        except Exception as e:
            print(f"Master Bot Main Loop Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
