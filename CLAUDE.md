# sui-portfolio-app (FORCE CAPITAL) プロジェクトルール

Claude Code が自動読み込みするプロジェクト固有ルール。違反しそうな作業では実行前に必ずユーザーに確認すること。

## デプロイ（最重要）

- 本アプリは Streamlit Community Cloud で稼働中。**main への push = 即本番デプロイ**
- push はユーザーの明示承認後のみ。push 前に必ず差分を報告する
- 2FA(TOTP) は一時無効化中（`_verify_totp()` は温存）。一般公開前に再有効化必須

## Secrets

- 秘密情報はすべて st.secrets（Streamlit Cloud 側）経由。コード直書き禁止
- `.streamlit/secrets.toml` はローカルに存在しても読まない・コミットしない
- 登録済みキー: gcp_credentials / jquants_api_key / users(bcrypt) / sheet_ids

## データ整合性

- 保有データの正は Google Sheets（data.py の sheet_ids）。シート名・列構成の変更は事前承認
- portfolio.csv は保有実データを含む追跡ファイル。リポジトリの public 化禁止
- NISA 枠の投信数量は「口数 ÷ 10,000」換算。calc 系変更時にこの換算を壊さない
- 外国株投信（オルカン・SBI-V 等）は実質通貨 USD 相当として集計

## テスト

- calc.py / data.py に触れたら `python -m pytest test_calc.py` を通してから報告
