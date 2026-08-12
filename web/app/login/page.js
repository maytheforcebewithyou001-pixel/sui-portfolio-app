"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { login } from "../../lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(username, password);
      router.push("/");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <form className="loginbox" onSubmit={onSubmit}>
        <h1>&lt; FORCE &gt; CAPITAL</h1>
        <label htmlFor="username">ユーザー名</label>
        <input id="username" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
        <label htmlFor="password">パスワード</label>
        <input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        <button className="primary" type="submit" disabled={busy}>
          {busy ? "認証中..." : "ログイン"}
        </button>
        {error && <p className="err">{error}</p>}
      </form>
    </main>
  );
}
