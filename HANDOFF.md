# FORCE CAPITAL - 引き継ぎメモ

最終更新: 2026-04-06

## プロジェクト概要

- **名称**: FORCE CAPITAL
- **種類**: 個人投資家向けポートフォリオ管理ツール（Streamlitアプリ）
- **リポジトリ**: `maytheforcebewithyou001-pixel/sui-portfolio-app`
- **デプロイ先**: Streamlit Community Cloud
- **運用フェーズ**: Phase 2（限定β、admin運用開始段階）

## 技術スタック

- **フロント/バック**: Streamlit (Python)
- **DB**: Google Sheets（ユーザー別に `PortfolioData_{username}`）
- **認証**: bcrypt パスワード + TOTP (optional) / Google OAuth (st.login)
- **価格取得**: J-Quants V2（日本株） / yfinance（米国株・指数・為替）
- **AI総評**: Claude API

## ファイル構成（主要）

```
ポートフォリオ/
├── app.py                   # メインUI・認証
├── config.py                # 定数
├── data.py                  # Google Sheets データ層
├── market.py                # 価格取得
├── calc.py                  # 計算エンジン
├── jquants.py               # J-Quants API
├── style.py                 # CSS
├── components.py            # 共通UI部品
├── tabs/
│   ├── tab_portfolio.py     # ポートフォリオ
│   ├── tab_analysis.py      # 分析
│   ├── tab_dividend.py      # 配当
│   ├── tab_simulation.py    # シミュレーション
│   ├── tab_market.py        # 世界指標
│   ├── tab_transaction.py   # 取引履歴
│   ├── tab_ai.py            # AI総評
│   └── tab_admin.py         # 管理者専用
├── requirements.txt
├── .github/workflows/pip-audit.yml  # 月次脆弱性スキャン
└── HANDOFF.md               # このファイル
```

## 認証・認可の仕組み

### ログイン方法（2通り）

1. **パスワード認証**
   - ユーザー名 + bcryptハッシュ検証
   - （オプション）TOTP 6桁コード
2. **Google OAuth**
   - `st.login()` で Google サインイン
   - メール→ユーザー名マッピングで admin 識別
   - Google側でパスキー設定済みならパスキー認証になる

### Streamlit Cloud Secrets 構造

```toml
# スカラー変数
jquants_api_key = "..."
anthropic_api_key = "..."
admin_users = ["admin"]

gcp_credentials = '''
{ ... GCPサービスアカウント JSON ... }
'''

# Google OAuth
[auth]
redirect_uri = "https://<app-url>.streamlit.app/oauth2callback"
cookie_secret = "..."
client_id = "...apps.googleusercontent.com"
client_secret = "GOCSPX-..."
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"

# ユーザー別パスワードハッシュ
[users]
admin = "$2b$12$..."

# TOTP シークレット（オプション）
[users_totp]
admin = "BASE32_SECRET"

# Google メール → ユーザー名 マッピング
[google_admin_map]
"your-email@gmail.com" = "admin"

# ユーザー別スプレッドシートID（推奨・同名重複対策）
[sheet_ids]
admin = "1aBcDeFgHiJkLmNoPqRsTuVwXyZ..."
```

> **注意**: `[sheet_ids]` は任意だが設定を推奨。未設定の場合はシート名で検索し、
> 同名スプレッドシートが複数あるとエラーで停止する。
> 新規シート作成時に画面にIDが表示されるので、その値を設定すること。

### データ分離

- 各ユーザーは `PortfolioData_{username}` という専用 Google Sheets を持つ
- `[sheet_ids]` にスプレッドシートIDが設定されていれば ID で開く（推奨）。未設定の場合は名前で検索し、同名重複があればエラー停止する
- `_load_all_sheets_cached(user)` でキャッシュをユーザー別にキー分離
- 初回ログイン時にシート自動作成（ヘッダー付き）→ 管理画面にIDが表示されるので `[sheet_ids]` に追記すること

## ユーザー追加手順

1. admin でログイン → 👑管理者タブ
2. 「新規ユーザーのパスワードハッシュ生成」フォームで入力
3. 出力された **1行** を Secrets の既存 `[users]` セクション末尾に追記（`[users]` ヘッダーは追加しない）
4. 管理者権限を付与した場合は `admin_users = [...]` 行も画面の指示どおり置き換え
5. （任意）「TOTP 2FA セットアップ」で生成された **1行** を既存 `[users_totp]` セクション末尾に追記（セクションが無い場合のみヘッダー行 `[users_totp]` を先に追加）
6. 保存 → アプリ自動再起動
7. 新ユーザー初回ログイン時にシート自動作成 → 画面に表示されるスプレッドシートIDを `[sheet_ids]` に追記

> **⚠ TOML 注意**: `[users]` や `[users_totp]` などのテーブルヘッダーを重複して貼ると Secrets 全体が壊れます。
> 管理画面の出力はヘッダーを含まない1行だけなので、そのまま該当セクション末尾に貼ってください。

## セキュリティ対策（実装済み）

- bcrypt パスワードハッシュ化（rounds=12）
- hmac.compare_digest でタイミング攻撃対策
- 指数バックオフ（ログイン失敗最大30秒遅延、5回で停止）
- セッションTTL（2時間）
- XSS対策（銘柄名等を html.escape）
- 監査ログ（ログイン成功・失敗を logger に記録）
- TOTP 2FA（オプション）
- Google OAuth + パスキー対応
- 月次 pip-audit（GitHub Actions）

## 運用メモ

### 定期メンテナンス

- **毎月1日**: GitHub Actions で pip-audit 自動実行（Actions タブで確認）
- **90日ごと**: GCPサービスアカウントキーのローテーション推奨
- **6ヶ月ごと**: adminパスワード変更推奨

### トラブルシューティング

| 症状 | 原因候補 |
|---|---|
| `invalid_grant: account not found` | GCPサービスアカウント削除/キー失効 |
| `redirect_uri_mismatch` | Google Cloud側とSecrets側のURLが不一致 |
| `このGoogleアカウントは許可されていません` | `google_admin_map` に未登録 |
| `bcrypt ValueError` | ハッシュ形式が無効 |
| シート読めない | サービスアカウントに共有権限なし |

### バックアップ

- 管理者タブ → 「現在ユーザーのシートをCSVバックアップ」
- ポートフォリオ・履歴・取引履歴の3種をダウンロード可能

## 今後のタスク（Phase 2 継続）

- β招待ユーザー募集（5〜10名）
- 競合調査スプシ作成（マネーフォワードME / Moneytree / カビュウ等）
- ニーズ検証インタビュー（5〜10名）
- フィードバック収集 → Phase 3 移行判断

## Phase 3 移行時の検討事項

- **技術**: Next.js + FastAPI + Supabase Postgres への移行
- **決済**: Stripe月額サブスク
- **認証**: Supabase Auth or Clerk（パスキー標準サポート）
- **法務**: 金融商品取引法（投資助言業登録の要否）、個人情報保護法対応
- **ホスティング**: Vercel + Cloud Run

## 重要な注意事項

- **秘密情報は絶対にチャットに貼らない**（過去のインシデント参照）
- **Google OAuth同意画面は「本番」状態を維持**（テスト中だと7日で失効）
- **GCPサービスアカウントは現在1つが全ユーザーのシートを操作**（Phase 3でユーザー別に分離）
- **Streamlit Cloud の Secrets はアプリから書き換え不可**、Secrets UIから手動更新のみ

## GCP プロジェクト情報

- プロジェクト名: My First Project
- プロジェクトID: `wide-maxim-491005-q9`
- サービスアカウント: `portfolio-bot@wide-maxim-491005-q9.iam.gserviceaccount.com`
- 有効API: Google Sheets API / Google Drive API

## 連絡先

- 管理者メール: may.the.force.be.with.you001@gmail.com

## 修正履歴（2026-04-09 実施）

レビュー3件＋ドキュメント整合性の追加修正を実施。

### 1. TOML スニペット修正 — `tabs/tab_admin.py`

- パスワードハッシュ出力から `[users]` テーブルヘッダーを除去し、追記用の1行のみ出力するよう変更
- TOTP シークレット出力から `[users_totp]` テーブルヘッダーを同様に除去
- 両方に `st.warning` で「ヘッダー行を重複して貼らないこと」を明示
- 管理者権限付与時は `admin_users` 行の置き換えとハッシュ追記をステップ分けして表示
- 管理画面冒頭の常時案内を「そのまま貼れる形式です」に統一（`[sheet_ids]` セクションごと出すケースとの矛盾を解消）

### 2. Google Sheets 同名重複対策 — `data.py`

- `_get_sheet_id_for(user)` を新設。Secrets の `[sheet_ids]` セクションにIDがあれば `open_by_key()` で確実に開く
- ID未設定時は `gc.openall(name)` で同名チェック。2件以上ある場合は候補IDを提示してエラー停止
- 新規シート作成時にスプレッドシートIDと `[sheet_ids]` 追記用スニペットを画面に表示
- 管理画面のシート事前作成ボタンでも作成後にIDスニペットを表示（`[sheet_ids]` セクション未作成時はヘッダーごと出力）

### 3. バックアップ CSV 除外 — `.gitignore`

- `portfolio_*.csv` / `history_*.csv` / `transactions_*.csv` / `backups/` を除外対象に追加

### 4. HANDOFF.md 整合性

- Secrets 構造に `[sheet_ids]` セクションの説明を追加
- データ分離セクションにID優先・同名重複エラーの挙動を記載
- ユーザー追加手順を「1行追記」方式に書き換え、ヘッダー重複禁止の注意書きを追加
