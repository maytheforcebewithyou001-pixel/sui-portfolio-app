"""日次資産記録ジョブ (Cloud Run Jobs エントリポイント)

Cloud Scheduler が毎朝 07:00 JST に起動し、その時点の評価額(現金込み・
totals.total_asset_all)を HistoryData シートへ追記する。PC 不要のクラウド完結版
(ローカルの scripts/daily_history_record.py は 07:30 のバックアップに降格)。

- 計算は api.service.build_snapshot = 本番 /api/portfolio と同一経路
  (marketstore の朝境界 06:10 更新もこの実行が兼ねる)
- 追記は data.save_history = Streamlit 版「💾 記録」ボタンと同一経路・同一書式
- 同日の行が既にあればスキップ(手動記録・ローカルバックアップとの二重追記防止)
- コンテナは UTC のため日付は JST 明示。失敗時は非ゼロ終了で
  Cloud Run のジョブ実行履歴に failed として残る

実行: python -m api.history_job
必要 env: GCP_CREDENTIALS_JSON / FC_SHEET_IDS_JSON / JQUANTS_API_KEY / FC_API_USER=admin
"""
import os
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))


def main() -> None:
    os.environ.setdefault("FC_API_USER", "admin")
    from api.service import build_snapshot
    from data import load_history, save_history

    today = datetime.now(JST).strftime("%Y/%m/%d")
    total = float(build_snapshot()["totals"]["total_asset_all"])

    if today in set(load_history()["日付"].astype(str)):
        print(f"SKIP: {today} は記録済み (評価額 {total:,.0f} 円)")
        return
    save_history(today, total)
    # save_history は例外を握りつぶすため、再読込で追記成立を確認する
    if today not in set(load_history()["日付"].astype(str)):
        raise RuntimeError("save_history 後の再読込で当日行が見つからない(書込失敗)")
    print(f"OK: {today} に {total:,.0f} 円を記録")


if __name__ == "__main__":
    main()
