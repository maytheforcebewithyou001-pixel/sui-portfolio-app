"""市場データ温めジョブ (Cloud Run Jobs エントリポイント)

Cloud Scheduler が毎日 18:10 JST に起動し、日本市場の自動更新境界(18:00)を越えて
陳腐化した MarketCache の日本株セグメントをライブ取得で温める。これにより
18:00 以降の初回アクセスで発生していた日本株約20銘柄の取得待ち(20秒前後)を
ユーザーの画面から消す(米国側の 06:00 境界は 07:00 の fc-history-record が兼ねる)。

- 経路は本番 /api/portfolio と同一(api.service._compute_state → marketstore.get_market_bundle)。
  ポリシー層がセグメント単位で鮮度判定するため、温め済みなら何も取得せず終わる(冪等)
- FC_SHEET_IDS_JSON に登録された全ユーザー分を順に回す。MarketCache の列はユーザー間の
  和集合で保持されるので、ユーザー固有の銘柄もこの1回で温まる
- 1ユーザーの失敗は他ユーザーの処理を止めない。失敗が1件でもあれば非ゼロ終了で
  Cloud Run のジョブ実行履歴に failed として残す
- MarketCache のシートID解決は marketstore._cache_sheet_id(FC_SHEET_IDS_JSON[FC_API_USER] で
  フォールバック)。未解決なら温めが成立しないため WARN を出す

実行: python -m api.warm_job
必要 env: GCP_CREDENTIALS_JSON / FC_SHEET_IDS_JSON / JQUANTS_API_KEY / FC_API_USER=admin
"""
import json
import os
import sys
import time


def target_users() -> list:
    """温め対象ユーザー。FC_SHEET_IDS_JSON のキー(シートID登録済み)を昇順、無ければ FC_API_USER"""
    raw = os.environ.get("FC_SHEET_IDS_JSON", "")
    if raw:
        try:
            ids = json.loads(raw)
            if isinstance(ids, dict):
                users = sorted(u for u, sid in ids.items() if sid)
                if users:
                    return users
        except ValueError:
            print("WARN: FC_SHEET_IDS_JSON のJSONが不正(FC_API_USER のみ処理)")
    return [os.environ.get("FC_API_USER") or "default"]


def _fmt_fetched(fetched: dict) -> str:
    return ", ".join(f"{seg}={dt:%m/%d %H:%M}" for seg, dt in sorted(fetched.items())) or "(なし)"


def main() -> int:
    os.environ.setdefault("FC_API_USER", "admin")
    import data
    import marketstore
    from api.service import _compute_state

    if not marketstore._cache_sheet_id():
        print("WARN: MarketCache のシートIDを解決できません(FC_SHEET_ID / FC_SHEET_IDS_JSON 未設定) — 温めは保存されません")
    before = marketstore.load_persistent()[2]
    print(f"MarketCache 取得時刻(実行前): {_fmt_fetched(before)}")

    failures = []
    for user in target_users():
        token = data.set_request_user(user)
        t0 = time.monotonic()
        try:
            state = _compute_state()
            print(f"OK: {user}: {len(state['display_df'])}銘柄 / market_fetched_at={state['market_fetched_at']}"
                  f" / {time.monotonic() - t0:.1f}s")
        except Exception as e:  # 1ユーザーの失敗で他ユーザーを止めない
            failures.append(user)
            print(f"NG: {user}: {type(e).__name__}: {e}")
        finally:
            data.reset_request_user(token)

    after = marketstore.load_persistent()[2]
    print(f"MarketCache 取得時刻(実行後): {_fmt_fetched(after)}")
    if failures:
        print(f"FAILED: {', '.join(failures)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
