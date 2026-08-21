"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { clearToken } from "../lib/api";

// 市場開場判定(app.py:325 _is_market_open と同一仕様: 平日+取引時間のみ、祝日非考慮)
function isMarketOpen(tz, openMin, closeMin, now) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hour12: false,
    weekday: "short",
    hour: "numeric",
    minute: "numeric",
  }).formatToParts(now);
  const get = (t) => parts.find((p) => p.type === t)?.value;
  if (get("weekday") === "Sat" || get("weekday") === "Sun") return false;
  const t = (Number(get("hour")) % 24) * 60 + Number(get("minute"));
  return openMin <= t && t < closeMin;
}

const TABS = [
  { href: "/", label: "ポートフォリオ" },
  { href: "/history", label: "資産推移" },
  { href: "/analysis", label: "分析" },
  { href: "/currency", label: "通貨配分" },
  { href: "/dividend", label: "配当" },
  { href: "/simulation", label: "シミュレーション" },
  { href: "/lifeplan", label: "ライフプラン" },
  { href: "/ai", label: "AI総評" },
  { href: "/transactions", label: "取引履歴" },
  { href: "/market", label: "世界指標" },
  { href: "/rank", label: "ランク" },
  { href: "/settings", label: "設定" },
];

export default function TopBar({ loadedAt, marketFetchedAt, loading, onReload }) {
  const router = useRouter();
  const pathname = usePathname();
  const ts = marketFetchedAt || loadedAt;

  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  }, []);
  const jpOpen = isMarketOpen("Asia/Tokyo", 9 * 60, 15 * 60 + 30, now); // 東証 9:00-15:30
  const usOpen = isMarketOpen("America/New_York", 9 * 60 + 30, 16 * 60, now); // NYSE/NASDAQ 9:30-16:00

  return (
    <>
      <div className="topbar">
        <span className="logo">
          <span className="dim">&lt;</span> FORCE <span className="dim">&gt; CAPITAL</span>
        </span>
        <span className="spacer" />
        <span className={jpOpen ? "mkt-open" : "mkt-closed"}>
          {jpOpen ? "● 東証 開場中" : "○ 東証 閉場"}
        </span>
        <span className={usOpen ? "mkt-open" : "mkt-closed"}>
          {usOpen ? "● 米国 開場中" : "○ 米国 閉場"}
        </span>
        {ts && (
          <span className="ts">
            {marketFetchedAt ? "市場データ " : ""}
            {new Date(ts).toLocaleString("ja-JP")} 取得
          </span>
        )}
        <button className="ghost" onClick={onReload} disabled={loading}>
          {loading ? "更新中..." : "🔄 更新"}
        </button>
        <button
          className="ghost"
          onClick={() => {
            clearToken();
            router.push("/login");
          }}
        >
          ログアウト
        </button>
      </div>
      <nav className="tabnav">
        {TABS.map((t) => (
          <Link key={t.href} href={t.href} className={pathname === t.href ? "active" : ""}>
            {t.label}
          </Link>
        ))}
      </nav>
    </>
  );
}
