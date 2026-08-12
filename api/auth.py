"""API認証: 単一ユーザー bcrypt + HMAC署名トークン

環境変数:
  FC_AUTH_USERNAME      ログインユーザー名(既定 "admin")
  FC_AUTH_PASSWORD_HASH bcryptハッシュ(Streamlit版 [users] と同形式)
  FC_TOKEN_SECRET       トークン署名鍵(必須)
"""
import base64
import hashlib
import hmac
import json
import os
import time

import bcrypt

TOKEN_TTL_SEC = 2 * 60 * 60  # Streamlit版 SESSION_TTL_SEC と同じ2時間


def _secret() -> bytes:
    s = os.environ.get("FC_TOKEN_SECRET", "")
    if not s:
        raise RuntimeError("FC_TOKEN_SECRET が未設定です")
    return s.encode()


def verify_password(username: str, password: str) -> bool:
    expected_user = os.environ.get("FC_AUTH_USERNAME", "admin")
    pw_hash = os.environ.get("FC_AUTH_PASSWORD_HASH", "")
    if not pw_hash:
        return False
    user_ok = hmac.compare_digest(username.encode(), expected_user.encode())
    try:
        pw_ok = bcrypt.checkpw(password.encode(), pw_hash.encode())
    except ValueError:
        return False
    return user_ok and pw_ok


def issue_token(username: str) -> str:
    payload = json.dumps({"u": username, "exp": int(time.time()) + TOKEN_TTL_SEC}).encode()
    b64 = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    sig = hmac.new(_secret(), b64.encode(), hashlib.sha256).hexdigest()
    return f"{b64}.{sig}"


def verify_token(token: str):
    """有効ならユーザー名を返す。無効・期限切れ・改竄は None"""
    try:
        b64, sig = token.rsplit(".", 1)
        expected = hmac.new(_secret(), b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        pad = "=" * (-len(b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(b64 + pad))
        if payload.get("exp", 0) < time.time():
            return None
        return payload.get("u")
    except Exception:
        return None
