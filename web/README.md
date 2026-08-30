# FORCE CAPITAL Web (Phase 3 / P3-2)

Next.js 製フロントエンド。バックエンドは同リポジトリの FastAPI (`api/`)。

## ローカル起動

### 1. API (リポジトリ直下で)

PowerShell:

```powershell
$env:FC_TOKEN_SECRET="<ランダムな長い文字列>"
$env:FC_AUTH_PASSWORD_HASH="<bcryptハッシュ>"
$env:FC_API_USER="admin"
$env:FC_SHEET_ID="<スプレッドシートID>"
$env:GCP_CREDENTIALS_JSON=(Get-Content <サービスアカウントJSONのパス> -Raw)
$env:JQUANTS_API_KEY="<J-Quantsキー>"
python -m uvicorn api.main:app --port 8000
```

bcryptハッシュの生成:

```powershell
python -c "import bcrypt; print(bcrypt.hashpw(input('password: ').encode(), bcrypt.gensalt()).decode())"
```

### 2. Web (web/ で)

```powershell
cd web
npm install
npm run dev
```

http://localhost:3000 を開いてログイン。API の場所を変える場合は
`NEXT_PUBLIC_API_BASE`（既定 `http://localhost:8000`）を設定する。

## 構成

- `app/login/page.js` — ログイン(トークンは localStorage)
- `app/page.js` — ダッシュボード(評価額ヘッダー・大幅変動/集中リスクアラート・保有一覧)
- `lib/api.js` — APIクライアント(401で自動ログアウト)

アラート判定・損益%・年間配当(税引後)の計算は Streamlit 版 app.py と同一ロジック。
デプロイ(Vercel + Cloud Run)は P3-3 で対応。
