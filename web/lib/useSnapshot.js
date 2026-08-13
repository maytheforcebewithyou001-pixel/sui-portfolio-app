"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AuthError, fetchPortfolio } from "./api";

// スナップショット取得の共有フック。初回表示はキャッシュ利用、reload(true)で強制再取得
export function useSnapshot() {
  const router = useRouter();
  const [snap, setSnap] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(
    async (force = false) => {
      setLoading(true);
      setError("");
      try {
        const data = await fetchPortfolio(force);
        setSnap(data);
      } catch (err) {
        if (err instanceof AuthError) {
          router.push("/login");
          return;
        }
        setError(err.message);
      } finally {
        setLoading(false);
      }
    },
    [router]
  );

  useEffect(() => {
    load(false);
  }, [load]);

  return { snap, error, loading, reload: () => load(true) };
}
