// APIクライアント: トークン管理と fetch ラッパー
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

const TOKEN_KEY = "fc_token";

export function getToken() {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  window.localStorage.removeItem(TOKEN_KEY);
}

export class AuthError extends Error {}

export async function login(username, password) {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))).detail || `HTTP ${res.status}`;
    throw new Error(detail);
  }
  const data = await res.json();
  setToken(data.token);
  return data;
}

export async function apiFetch(path, options = {}) {
  const token = getToken();
  if (!token) throw new AuthError("未ログイン");
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  });
  if (res.status === 401) {
    clearToken();
    throw new AuthError("トークンが無効か期限切れです");
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export function apiPost(path, payload) {
  return apiFetch(path, { method: "POST", body: JSON.stringify(payload) });
}

// タブ間遷移で再フェッチしないためのモジュールキャッシュ(更新ボタンで force)
let _snapshot = null;

export async function fetchPortfolio(force = false) {
  if (!force && _snapshot) return _snapshot;
  const data = await apiFetch("/api/portfolio");
  _snapshot = { ...data, loadedAt: Date.now() };
  return _snapshot;
}

export function clearSnapshot() {
  _snapshot = null;
}
