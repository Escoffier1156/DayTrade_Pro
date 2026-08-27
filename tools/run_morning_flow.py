#!/usr/bin/env python3
import sys
import os

# Add the daytrade_pro directory to sys.path so we can import simple.bot
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from simple.bot import run_fetch_yesterday, run_morning_screener

def force_morning_run():
    print("=== 朝の自動起動フローを手動実行します ===")
    
    print("\n[Step 1] ユニバースデータ（前日の日足データ）の更新を開始します...")
    try:
        run_fetch_yesterday()
        print("✅ ユニバースデータの更新が完了しました。")
    except Exception as e:
        print(f"❌ ユニバースデータ更新エラー: {e}")
        return

    print("\n[Step 2] 本日のスクリーニング（大型株の抽出）を開始します...")
    try:
        run_morning_screener()
        print("✅ スクリーニングが完了しました。")
    except Exception as e:
        print(f"❌ スクリーニングエラー: {e}")
        return
        
    print("\n=== 全ての朝のフローが完了しました ===")
    print("※ 抽出された銘柄データは data/today_targets.json に保存され、")
    print("   daytrade-monitor サービスが自動的に監視（利確・損切）を引き継ぎます。")

if __name__ == "__main__":
    force_morning_run()
