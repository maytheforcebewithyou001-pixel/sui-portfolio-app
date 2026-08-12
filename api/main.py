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
from api.service import build_snapshot

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
