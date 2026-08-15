"""FORCE CAPITAL API (Phase 3 / P3-1)

起動: uvicorn api.main:app --reload
必要な環境変数: api/auth.py の docstring と GCP_CREDENTIALS_JSON / FC_API_USER / FC_SHEET_ID (data.py)
"""
import os
import time

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import data as data_layer
from api import auth
from api import service as svc
from api.service import build_snapshot, future_simulation_yearly, withdrawal_simulation

app = FastAPI(title="FORCE CAPITAL API", version="0.1.0")

_cors_origins = [o.strip() for o in os.environ.get("FC_CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ログイン失敗の指数バックオフ(Streamlit版と同様、最大30秒)。ユーザー別に管理し、
# 片方の連続失敗が他ユーザーのログインを巻き込まないようにする。
# 未知ユーザー名は "__unknown__" の1枠へ集約(辞書の無制限肥大防止)
_login_backoff: dict = {}  # key -> (fail_count, lock_until)


def _backoff_key(username: str) -> str:
    return username if username in auth.user_hashes() else "__unknown__"


class LoginRequest(BaseModel):
    username: str
    password: str


async def require_auth(authorization: str = Header(default="")):
    """Bearerトークンを検証し、認証ユーザーをデータ層のユーザーコンテキストへ設定する。

    シート解決(data._current_user)がログインユーザーに連動する要。応答後に必ずresetする。
    async必須: 同期依存はスレッドプールのコピーされたコンテキストで走るため、
    ContextVarの設定がエンドポイントに届かずresetも別コンテキストで失敗する
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="認証トークンがありません")
    user = auth.verify_token(authorization[len("Bearer "):])
    if not user or user not in auth.user_hashes():
        raise HTTPException(status_code=401, detail="トークンが無効か期限切れです")
    ctx = data_layer.set_request_user(user)
    try:
        yield user
    finally:
        data_layer.reset_request_user(ctx)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/auth/login")
def login(req: LoginRequest):
    key = _backoff_key(req.username)
    fail_count, lock_until = _login_backoff.get(key, (0, 0.0))
    now = time.time()
    if now < lock_until:
        raise HTTPException(status_code=429, detail=f"試行間隔を空けてください({int(lock_until - now) + 1}秒後に再試行)")
    if not auth.verify_password(req.username, req.password):
        fail_count += 1
        _login_backoff[key] = (fail_count, now + min(2 ** fail_count, 30))
        raise HTTPException(status_code=401, detail="ユーザー名またはパスワードが違います")
    _login_backoff.pop(key, None)
    return {"token": auth.issue_token(req.username), "expires_in": auth.TOKEN_TTL_SEC}


@app.get("/api/portfolio")
def portfolio(user: str = Depends(require_auth)):
    return build_snapshot()


class FutureSimRequest(BaseModel):
    initial: float
    annual_rate: float  # 例 0.06
    years: int
    yearly_addition: float


@app.post("/api/simulate/future")
def simulate_future(req: FutureSimRequest, user: str = Depends(require_auth)):
    if not (0 < req.years <= 60):
        raise HTTPException(status_code=422, detail="years は 1〜60 で指定")
    return {"rows": future_simulation_yearly(req.initial, req.annual_rate, req.years, req.yearly_addition)}


class WithdrawalSimRequest(BaseModel):
    initial: float
    annual_rate: float
    mode: str  # fixed | rate | inflation
    annual_withdrawal: float = 0.0
    withdrawal_rate: float = 0.0
    inflation_rate: float = 0.0
    max_years: int = 40


@app.post("/api/simulate/withdrawal")
def simulate_withdrawal_ep(req: WithdrawalSimRequest, user: str = Depends(require_auth)):
    if req.mode not in ("fixed", "rate", "inflation"):
        raise HTTPException(status_code=422, detail="mode は fixed/rate/inflation")
    if not (1 <= req.max_years <= 60):
        raise HTTPException(status_code=422, detail="max_years は 1〜60 で指定")
    return {"rows": withdrawal_simulation(req.initial, req.annual_rate, req.mode,
                                          req.annual_withdrawal, req.withdrawal_rate,
                                          req.inflation_rate, req.max_years)}


# ── AI総評 / ライフプラン ──

def _ai_errors(fn):
    try:
        return fn()
    except svc.AIKeyMissing as e:
        raise HTTPException(status_code=503, detail=str(e))
    except svc.AIGenerationError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/ai/review")
def ai_review(user: str = Depends(require_auth)):
    return svc.get_ai_review_state()


@app.post("/api/ai/review/generate")
def ai_review_generate(user: str = Depends(require_auth)):
    return _ai_errors(svc.generate_ai_review)


class PolicyMemoRequest(BaseModel):
    memo: str


@app.put("/api/ai/policy-memo")
def ai_policy_memo(req: PolicyMemoRequest, user: str = Depends(require_auth)):
    if len(req.memo) > 20000:
        raise HTTPException(status_code=422, detail="メモが長すぎます(20,000字まで)")
    svc.save_policy_memo(req.memo)
    return {"status": "ok"}


@app.get("/api/ai/lifeplan")
def ai_lifeplan(user: str = Depends(require_auth)):
    return svc.get_lifeplan_state()


class LifeplanRequest(BaseModel):
    inputs: dict


@app.post("/api/ai/lifeplan/generate")
def ai_lifeplan_generate(req: LifeplanRequest, user: str = Depends(require_auth)):
    if not req.inputs or len(req.inputs) > 30:
        raise HTTPException(status_code=422, detail="inputs が不正です")
    if any(not isinstance(k, str) or not isinstance(v, str) or len(v) > 2000 for k, v in req.inputs.items()):
        raise HTTPException(status_code=422, detail="inputs は文字列のキーと値(2,000字以内)で指定")
    return _ai_errors(lambda: svc.generate_lifeplan(req.inputs))


# ── 世界指標 / 投資部門フロー / ランク ──

@app.get("/api/market/indices")
def market_indices(period: str = "1ヶ月", user: str = Depends(require_auth)):
    if period not in svc.PERIOD_MAP:
        raise HTTPException(status_code=422, detail=f"period は {tuple(svc.PERIOD_MAP)} のいずれか")
    return svc.get_world_indices(period)


@app.get("/api/market/investor-flow")
def market_investor_flow(weeks: int = 12, user: str = Depends(require_auth)):
    if weeks not in (12, 26, 52):
        raise HTTPException(status_code=422, detail="weeks は 12/26/52 のいずれか")
    return svc.get_investor_flow(weeks)


@app.get("/api/rank")
def rank(user: str = Depends(require_auth)):
    return svc.get_rank_state()


# ── アプリ設定(Streamlit版サイドバー相当) ──

@app.get("/api/settings")
def get_settings(user: str = Depends(require_auth)):
    return svc.get_app_settings()


class SettingsRequest(BaseModel):
    target_jpy_pct: float | None = None
    target_usd_pct: float | None = None
    cash_balance_jpy: float | None = None


@app.put("/api/settings")
def put_settings(req: SettingsRequest, user: str = Depends(require_auth)):
    try:
        return svc.save_app_settings(req.target_jpy_pct, req.target_usd_pct, req.cash_balance_jpy)
    except svc.SettingsError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ── 取引履歴 ──
import base64  # noqa: E402

TX_TYPES = ("買い増し", "売却", "新規購入")
IMPORT_MODES = ("取引履歴に登録", "保有銘柄の数量を更新", "両方（取引履歴＋保有銘柄更新）")
MAX_CSV_BYTES = 5 * 1024 * 1024


def _tx_errors(fn):
    try:
        return fn()
    except svc.TxError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.get("/api/transactions")
def transactions(user: str = Depends(require_auth)):
    return svc.get_transactions_state()


class ManualTxRequest(BaseModel):
    index: int
    code: str
    tx_type: str
    date: str  # YYYY/MM/DD
    qty: float
    price: float
    fee: float = 0.0
    broker: str
    tax: str


@app.post("/api/transactions")
def transactions_record(req: ManualTxRequest, user: str = Depends(require_auth)):
    if req.tx_type not in TX_TYPES:
        raise HTTPException(status_code=422, detail=f"取引種別は {TX_TYPES} のいずれか")
    if not (0 < req.qty <= 100_000_000) or not (0 <= req.price <= 100_000_000) or not (0 <= req.fee <= 10_000_000):
        raise HTTPException(status_code=422, detail="数量/単価/手数料が範囲外です")
    import re
    if not re.match(r"^\d{4}/\d{2}/\d{2}$", req.date):
        raise HTTPException(status_code=422, detail="日付は YYYY/MM/DD 形式で指定")
    pnl = _tx_errors(lambda: svc.record_manual_transaction(
        req.index, req.code, req.tx_type, req.date, req.qty, req.price, req.fee, req.broker, req.tax))
    return {"pnl_realized": round(pnl, 0)}


class CsvRequest(BaseModel):
    content_b64: str


class CsvImportRequest(CsvRequest):
    mode: str


def _decode_csv_b64(content_b64: str) -> bytes:
    try:
        raw = base64.b64decode(content_b64, validate=True)
    except Exception:
        raise HTTPException(status_code=422, detail="content_b64 が不正です")
    if len(raw) > MAX_CSV_BYTES:
        raise HTTPException(status_code=422, detail="CSVが大きすぎます(5MBまで)")
    return raw


@app.post("/api/transactions/import/preview")
def transactions_import_preview(req: CsvRequest, user: str = Depends(require_auth)):
    raw = _decode_csv_b64(req.content_b64)
    return _tx_errors(lambda: svc.preview_broker_csv(raw))


@app.post("/api/transactions/import/execute")
def transactions_import_execute(req: CsvImportRequest, user: str = Depends(require_auth)):
    if req.mode not in IMPORT_MODES:
        raise HTTPException(status_code=422, detail=f"mode は {IMPORT_MODES} のいずれか")
    raw = _decode_csv_b64(req.content_b64)
    return _tx_errors(lambda: svc.execute_broker_csv(raw, req.mode))
