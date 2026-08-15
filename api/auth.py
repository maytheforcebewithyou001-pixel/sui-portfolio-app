"""API認証: ユーザー名→bcryptハッシュ辞書 + HMAC署名トークン

環境変数:
  FC_AUTH_USERS_JSON    {"ユーザー名": "bcryptハッシュ"} のJSON辞書(マルチユーザー)
  FC_AUTH_USERNAME      (互換) 単一ユーザー名(既定 "admin")。FC_AUTH_USERS_JSON 未設定時のみ有効
  FC_AUTH_PASSWORD_HASH (互換) bcryptハッシュ(Streamlit版 [users] と同形式)
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

# 未知ユーザー名でも1回bcrypt検証を通し、既知ユーザーと応答時間を揃える(ユーザー名列挙対策)
_DUMMY_HASH = bcrypt.hashpw(b"fc-timing-equalizer", bcrypt.gensalt(rounds=12))


def _secret() -> bytes:
    s = os.environ.get("FC_TOKEN_SECRET", "")
    if not s:
        raise RuntimeError("FC_TOKEN_SECRET が未設定です")
    return s.encode()


def user_hashes() -> dict:
    """認証可能な {ユーザー名: bcryptハッシュ}。

    FC_AUTH_USERS_JSON があればそれのみを使う(不正JSONは全拒否)。
    無ければ従来の単一ユーザー環境変数へフォールバック。
    """
    raw = os.environ.get("FC_AUTH_USERS_JSON", "")
    if raw:
        try:
            d = json.loads(raw)
        except ValueError:
            return {}
        if not isinstance(d, dict):
            return {}
        return {str(k): str(v) for k, v in d.items() if str(k) and str(v)}
    pw_hash = os.environ.get("FC_AUTH_PASSWORD_HASH", "")
    if not pw_hash:
        return {}
    return {os.environ.get("FC_AUTH_USERNAME", "admin"): pw_hash}


def verify_password(username: str, password: str) -> bool:
    pw_hash = user_hashes().get(username)
    if pw_hash is None:
        bcrypt.checkpw(password.encode(), _DUMMY_HASH)
        return False
    try:
        return bcrypt.checkpw(password.encode(), pw_hash.encode())
    except ValueError:
        return False


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
