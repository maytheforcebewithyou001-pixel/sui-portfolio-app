# -*- coding: utf-8 -*-
"""Streamlit Community Cloud keep-alive.

アプリのトップページをヘッドレスブラウザで開き、WebSocketセッションを確立して
「トラフィックあり」として計上させる。休止中なら Wake up ボタンを押して復帰させる。
ログインはしない（ログイン画面の表示だけでセッションは張られる）。
"""
import os
import re
import sys
import time

from playwright.sync_api import sync_playwright

URL = os.environ["KEEPALIVE_URL"]
WAKE_PATTERN = re.compile(r"(get this app back up|wake)", re.IGNORECASE)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(10_000)

        # 休止中なら復帰ボタンを押す
        for frame in page.frames:
            try:
                btn = frame.get_by_role("button", name=WAKE_PATTERN)
                if btn.count() > 0:
                    print("app is hibernating -> waking up")
                    btn.first.click()
                    page.wait_for_timeout(120_000)  # 起動待ち
                    break
            except Exception:
                continue

        # Streamlitランタイムの読み込みを確認（DOM構造のバージョン差に備え複数候補＋動的タイトル）
        deadline = time.time() + 180
        ok = False
        while time.time() < deadline:
            if page.locator(
                '.stApp, [data-testid="stApp"], [data-testid="stAppViewContainer"]'
            ).count() > 0 or "· Streamlit" in page.title():
                ok = True
                break
            page.wait_for_timeout(5_000)

        # セッションを少し維持してから終了
        page.wait_for_timeout(20_000)
        title = page.title()
        browser.close()

    print(f"title={title!r} streamlit_runtime={'OK' if ok else 'NOT FOUND'}")
    if not ok:
        print("::warning::Streamlit runtime not detected — check the app URL / status")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
