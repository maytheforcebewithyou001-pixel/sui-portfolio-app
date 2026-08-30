# sui-portfolio-app (FORCE CAPITAL) プロジェクトルール

Claude Code が自動読み込みするプロジェクト固有ルール。違反しそうな作業では実行前に必ずユーザーに確認すること。

## 構成（2026-08-30 Streamlit退役済み）

- フロント: `web/`（Next.js、Vercel `sui-portfolio-app.vercel.app`。main への push で自動デプロイ）
- API: `api/`（FastAPI、Cloud Run `fc-api`。デプロイは `scripts/deploy_*.ps1` からの手動実行のみ）
- 日次記録: Cloud Run Job `fc-history-record`（07:00 JST、`api/history_job.py`）
- 旧 Streamlit 版（app.py / tabs/）は削除済み。共有ロジックはルート直下の
  `ai_review.py` / `investor_flow.py` / `fin_view.py` / `transactions.py` / `cacheutil.py` に切り出し済み

## デプロイ（最重要）

- **web/ は main への push = Vercel 即本番デプロイ**。push はユーザーの明示承認後のみ。push 前に必ず差分を報告する
- Cloud Run（fc-api / fc-history-record）は push では更新されない。API 側を変更したら再デプロイの要否を報告する
- デプロイの罠: `.gcloudignore` と Dockerfile の COPY 対象を点検（新モジュール追加時に漏れやすい）

## Secrets

- 秘密情報はすべて環境変数（Cloud Run の Secret 参照 / ローカルは env）経由。コード直書き禁止
- 主要キー: GCP_CREDENTIALS_JSON / FC_SHEET_IDS_JSON / JQUANTS_API_KEY / FC_AUTH_USERS_JSON / FC_TOKEN_SECRET / ANTHROPIC_API_KEY

## データ整合性

- 保有データの正は Google Sheets（data.py のシートID解決）。シート名・列構成の変更は事前承認
- portfolio.csv は保有実データを含む追跡ファイル。リポジトリの public 化禁止
- NISA 枠の投信数量は「口数 ÷ 10,000」換算。calc 系変更時にこの換算を壊さない
- 外国株投信（オルカン・SBI-V 等）は実質通貨 USD 相当として集計

## テスト

- calc.py / data.py に触れたら `python -m pytest test_calc.py` を通してから報告
- api/ / 共有モジュールに触れたら `python -m pytest test_api.py` も通す
