"""FORCE CAPITAL API (Phase 3 / P3-1)

起動: uvicorn api.main:app --reload
必要な環境変数: api/auth.py の docstring と GCP_CREDENTIALS_JSON / FC_API_USER / FC_SHEET_ID (data.py)
"""
import os
import time

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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

# ログイン失敗の指数バックオフ(Streamlit版と同様、最大30秒・単一ユーザー前提の簡易版)
_fail_count = 0
_lock_until = 0.0


class LoginRequest(BaseModel):
    username: str
    password: str


def require_auth(authorization: str = Header(default="")) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="認証トークンがありません")
    user = auth.verify_token(authorization[len("Bearer "):])
    if not user:
        raise HTTPException(status_code=401, detail="トークンが無効か期限切れです")
    return user


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/auth/login")
def login(req: LoginRequest):
    global _fail_count, _lock_until
    now = time.time()
    if now < _lock_until:
        raise HTTPException(status_code=429, detail=f"試行間隔を空けてください({int(_lock_until - now) + 1}秒後に再試行)")
    if not auth.verify_password(req.username, req.password):
        _fail_count += 1
        _lock_until = now + min(2 ** _fail_count, 30)
        raise HTTPException(status_code=401, detail="ユーザー名またはパスワードが違います")
    _fail_count = 0
    _lock_until = 0.0
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
