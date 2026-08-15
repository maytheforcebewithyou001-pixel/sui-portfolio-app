"""ユーザー別スプレッドシート作成/初期化スクリプト (P3-4 マルチユーザー用)

⚠ サービスアカウント(SA)のDrive容量は0のため gc.create は 403 で失敗する
(2026-08-15実測: "The user's Drive storage quota has been exceeded")。
そのため運用は「ユーザー本人がDriveで空シートを作成 → SAのメールに編集者共有 →
本スクリプト --id でヘッダー初期化」。data.py の名前解決による初回自動作成も
同じ理由で動かないので、新規ユーザーは FC_SHEET_IDS_JSON への事前登録が必須。

外部通信あり(Google Sheets / Drive)。

使い方(リポジトリ直下):
  既存シートの初期化: python scripts/create_user_sheet.py --id <シートID>
  SA直作成(容量が戻った場合のみ): python scripts/create_user_sheet.py --user naoya --share <メール>
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import gspread
from google.oauth2.service_account import Credentials

from config import EXPECTED_COLS

DEFAULT_CREDS = r"C:\Users\mayth\Documents\stock_backtest\credentials\gsa_key.json"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", default=None, help="ユーザー名(シート名サフィックス)。SA直作成モード")
    parser.add_argument("--id", default=None, help="既存スプレッドシートID。ヘッダー初期化モード")
    parser.add_argument("--share", default=None, help="編集権限を付与するGoogleアカウント")
    parser.add_argument("--creds", default=DEFAULT_CREDS, help="GCPサービスアカウントJSONのパス")
    args = parser.parse_args()
    if bool(args.user) == bool(args.id):
        parser.error("--user (SA直作成) か --id (既存初期化) のどちらか一方を指定")

    raw = os.environ.get("GCP_CREDENTIALS_JSON", "")
    if not raw:
        with open(args.creds, encoding="utf-8") as f:
            raw = f.read()
    creds = Credentials.from_service_account_info(
        json.loads(raw),
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"],
    )
    gc = gspread.authorize(creds)

    if args.id:
        sh = gc.open_by_key(args.id)
        ws = sh.sheet1
        vals = ws.get_all_values()
        if vals:
            print(f"✗ シート '{sh.title}' (id={sh.id}) の先頭シートは空ではありません({len(vals)}行)。初期化を中止。")
            raise SystemExit(1)
        ws.update_title("PortfolioData")
        ws.update("A1", [EXPECTED_COLS], value_input_option="RAW")
        print(f"✓ 初期化完了: '{sh.title}' (id={sh.id})")
        print(f"  メインシート名=PortfolioData、ヘッダー{len(EXPECTED_COLS)}列を書き込み")
        print()
        print("FC_SHEET_IDS_JSON への登録例(シートIDは秘密情報ではない):")
        print(f'  {{"admin": "<現行のFC_SHEET_ID>", "<ユーザー名>": "{sh.id}"}}')
        return

    name = f"PortfolioData_{args.user}"
    existing = gc.openall(name)
    if existing:
        print(f"✗ '{name}' は既に {len(existing)} 件存在します。作成を中止。")
        for s in existing:
            print(f"  id={s.id}")
        raise SystemExit(1)

    sh = gc.create(name)
    ws = sh.sheet1
    ws.update_title("PortfolioData")
    ws.update("A1", [EXPECTED_COLS], value_input_option="RAW")
    print(f"✓ 作成: {name}")
    print(f"  id: {sh.id}")
    print(f"  url: https://docs.google.com/spreadsheets/d/{sh.id}")

    if args.share:
        sh.share(args.share, perm_type="user", role="writer", notify=False)
        print(f"✓ 共有: {args.share} (編集者)")

    print()
    print("FC_SHEET_IDS_JSON への登録例(シートIDは秘密情報ではない):")
    print(f'  {{"admin": "<現行のFC_SHEET_ID>", "{args.user}": "{sh.id}"}}')


if __name__ == "__main__":
    main()
