# P3-3 デプロイ手順書 (Cloud Run + Vercel)

作成: 2026-08-14 / 前提: PHASE3_PLAN.md §4 P3-3

> **原則**: 本手順のうち「アカウント操作を伴う工程」は岡部が実行する。Claudeはコード生成・検証・設定値の準備までを担当する。
> **秘密情報はこのファイルに書かない**（キー名のみ記載する）。

---

## 0. 事前準備（岡部の作業・各1回のみ）

| # | 作業 | 補足 |
|---|---|---|
| 0-1 | Google Cloud SDK をインストール | https://cloud.google.com/sdk/docs/install-sdk（Windows用インストーラ） |
| 0-2 | `gcloud auth login` | ブラウザ認証。プロンプトに `! gcloud auth login` で実行可 |
| 0-3 | `gcloud config set project wide-maxim-491005-q9` | 既存GCPプロジェクトを流用 |
| 0-4 | Vercelアカウントを GitHub と連携 | https://vercel.com/new から `sui-portfolio-app` を選択（CLI不要） |

課金の目安: Cloud Run は min-instances=0（scale-to-zero）で個人利用なら**月0円圏**（無料枠 200万リクエスト/月）。Vercel Hobby も無料。Secret Manager は 6シークレット×$0.06/月 ≒ **月0.4$程度**。

---

## 1. Secrets 移設一覧（値はチャット・ファイルに貼らない）

Streamlit Cloud Secrets / ローカル .env から Cloud Run へ移す。**キー単位でチェックすること**（PHASE3_PLAN §5 のリスク対応）。

| # | 環境変数名 | 現在の在処 | 用途 | 必須 |
|---|---|---|---|---|
| 1 | `GCP_CREDENTIALS_JSON` | `stock_backtest\credentials\gsa_key.json` の中身 | Sheets 読み書き | ✅ |
| 2 | `FC_SHEET_ID` | 定数（保有スプレッドシートID） | データ源の指定 | ✅ |
| 3 | `FC_API_USER` | `admin` | シート名のサフィックス解決 | ✅ |
| 4 | `FC_TOKEN_SECRET` | **新規発行**（`openssl rand -hex 32` 相当） | トークン署名鍵 | ✅ |
| 5 | `FC_AUTH_USERNAME` | `admin` | ログインユーザー名 | ✅ |
| 6 | `FC_AUTH_PASSWORD_HASH` | Streamlit Secrets `[users]` の bcrypt ハッシュ | ログインパスワード | ✅ |
| 7 | `JQUANTS_API_KEY` | `stock_backtest\.env` | 世界指標タブの投資部門フロー | 任意 |
| 8 | `ANTHROPIC_API_KEY` | `stock_backtest\.env` | AI総評・ライフプラン生成 | 任意 |
| 9 | `FC_CORS_ORIGINS` | 新規（Vercel の本番URL） | CORS許可元 | ✅ |

> `FC_TOKEN_SECRET` を変えると既存ログインは全て無効化される（トークン署名が変わるため）。ローカル検証で毎回再ログインが必要だったのはこの仕様。

### 1-b. マルチユーザー化（P3-4 父アカウント・案A）で追加された環境変数

| # | 環境変数名 | 形式 | 用途 |
|---|---|---|---|
| 10 | `FC_AUTH_USERS_JSON` | `{"admin": "<bcryptハッシュ>", "<父ユーザー名>": "<bcryptハッシュ>"}` | マルチユーザー認証辞書。**設定すると #5/#6 は無視される**。ハッシュを含むため Secret Manager 登録（例: `fc-auth-users`） |
| 11 | `FC_SHEET_IDS_JSON` | `{"admin": "<シートID>", "<父ユーザー名>": "<父シートID>"}` | ユーザー別スプレッドシートID。シートIDは秘密情報ではないため `--set-env-vars` でよい |

挙動の要点:

- **後方互換**: #10/#11 を設定しない限り従来の単一ユーザー構成（#2/#3/#5/#6）のまま動く。現行本番は無変更で影響ゼロ
- **ID漏洩防止**: 単一ユーザー互換の `FC_SHEET_ID` は `FC_API_USER` と一致するユーザーにしか適用されない。父ログインが admin のシートへ到達する経路は存在しない（test_api.py `TestUserContext` / `TestMultiUserEndpoints` で担保）
- ログインユーザーは HMAC トークンに入り、リクエスト単位の ContextVar 経由で `data._current_user()` に届く（環境変数 `FC_API_USER` より優先）
- `FC_SHEET_IDS_JSON` に無いユーザーは名前解決（`PortfolioData_<ユーザー名>`）になり、初回アクセス時にサービスアカウントの Drive に**空シートが自動作成される**。父シートは事前に作成して ID を登録する運用を推奨
- 認証辞書から削除したユーザーは、発行済みトークンが期限内でも 401 になる（require_auth で照合）
- 父パスワードのハッシュ生成: `python -c "import bcrypt,getpass; print(bcrypt.hashpw(getpass.getpass().encode(), bcrypt.gensalt()).decode())"`（値はチャット非経由でパイプ直行）

---

## 2. Cloud Run へデプロイ（岡部が実行）

リポジトリ直下で。`--source .` を使うと Dockerfile が自動採用される。

```
gcloud run deploy fc-api ^
  --source . ^
  --region asia-northeast1 ^
  --platform managed ^
  --allow-unauthenticated ^
  --min-instances 0 ^
  --memory 1Gi ^
  --timeout 300 ^
  --set-env-vars FC_API_USER=admin,FC_SHEET_ID=<シートID>,FC_AUTH_USERNAME=admin ^
  --set-secrets GCP_CREDENTIALS_JSON=fc-gcp-creds:latest,FC_TOKEN_SECRET=fc-token-secret:latest,FC_AUTH_PASSWORD_HASH=fc-auth-hash:latest,JQUANTS_API_KEY=fc-jquants-key:latest,ANTHROPIC_API_KEY=fc-anthropic-key:latest
```

シークレットは事前に Secret Manager へ登録しておく（値は画面から貼る）:

```
gcloud secrets create fc-token-secret --replication-policy=automatic
gcloud secrets versions add fc-token-secret --data-file=-
```

**`--allow-unauthenticated` について**: アプリ側で bcrypt+HMACトークン認証をしているため、Cloud Run 側は公開でよい。ただし `/api/health` は無認証で応答する（監視用・情報漏洩なし）。

メモリ1Giの根拠: pandas+yfinance+streamlit を読み込むため 512Mi では起動時にOOMの懸念がある。実測後に下げてよい。

---

## 3. Vercel へデプロイ（岡部が実行）

1. https://vercel.com/new → `sui-portfolio-app` を Import
2. **Root Directory を `web` に設定**（重要・リポジトリ直下ではない）
3. Environment Variables に以下を追加:
   - `NEXT_PUBLIC_API_BASE` = Cloud Run のURL（例 `https://fc-api-xxxxx.a.run.app`）
4. Deploy

デプロイ後、Cloud Run 側の `FC_CORS_ORIGINS` に Vercel の本番URLを設定して再デプロイ:

```
gcloud run services update fc-api --region asia-northeast1 ^
  --update-env-vars FC_CORS_ORIGINS=https://<vercel-app>.vercel.app
```

---

## 4. デプロイ後の確認（Claudeが実施可能）

```
# 1. ヘルスチェック（無認証）
curl https://fc-api-xxxxx.a.run.app/api/health   → {"status":"ok"}

# 2. ログイン → /api/portfolio が 200 で返る
# 3. Vercel URL を開いてログイン → 9タブすべて表示
# 4. Streamlit版と評価額・損益・配当の3点一致を確認（P3-4の日次チェック開始）
```

---

## 5. 既知の注意点

- **コールドスタート**: min-instances=0 のため初回アクセスは 5〜15秒かかる（イメージにpandas等を含むため）。体感が悪ければ `--min-instances 1`（月数百円）へ。
- **イメージのスリム化は完了(2026-08-30)**: Streamlit退役に伴い共有関数を `ai_review.py` / `investor_flow.py` / `fin_view.py` / `transactions.py` へ切り出し、streamlit/plotly/Authlib/pyotp/qrcode を依存から削除済み。
- **J-Quants CLI は同梱していない**: コンテナでは HTTP API 経路になる（`JQUANTS_API_KEY` 必須）。
- **ログイン失敗のバックオフはインスタンス単位**: `api/main.py` の失敗カウンタはプロセス内変数のため、複数インスタンスに分散すると総当たり耐性が落ちる。単一ユーザー・低トラフィック前提では実害は小さいが、公開範囲を広げる場合は Cloud Armor か外部ストア方式へ変更すること。
- **並行運用中の変更凍結**: PHASE3_PLAN §5 の通り、P3-4 完了までは機能追加を止めバグ修正のみ両系へ適用する。

---

## 6. 市場データ温め Job（fc-market-warm、2026-09-04 追加）

日本株の自動更新境界（JST 18:00）を越えた直後の初回アクセスで発生していた日本株約20銘柄のライブ取得待ちを、
Scheduler 起動の Job が 18:10 に先回りして解消する。米国側（06:00 境界）は 07:00 の fc-history-record が兼ねる。

```
powershell -ExecutionPolicy Bypass -File scripts\deploy_warm_job.ps1
```

- 実体は `api/warm_job.py`（`python -m api.warm_job`）。本番 `/api/portfolio` と同一経路（`api.service._compute_state`）で
  `FC_SHEET_IDS_JSON` の全ユーザー分を順に温める。温め済みなら何も取得せず終わる（冪等）
- Secrets / env は fc-history-record と同一（fc-gcp-creds / fc-sheet-ids / fc-jquants-key、`FC_API_USER=admin`）
- **MarketCache のシートID解決**: Job には `FC_SHEET_ID` を渡していないため、`marketstore._cache_sheet_id` が
  `FC_SHEET_IDS_JSON[FC_API_USER]` へフォールバックする（2026-09-04 追加）。この修正は fc-history-record にも効くので、
  **両 Job を再デプロイ**すること（`deploy_history_job.ps1` を再実行）
- 手動試験: `gcloud run jobs execute fc-market-warm --region asia-northeast1 --wait`。ログに
  「MarketCache 取得時刻(実行前/実行後)」が出るので、jp の時刻が更新されれば成功
