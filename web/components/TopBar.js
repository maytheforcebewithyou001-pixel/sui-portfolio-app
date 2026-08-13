"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clearToken } from "../lib/api";

const TABS = [
  { href: "/", label: "ポートフォリオ" },
  { href: "/analysis", label: "分析" },
  { href: "/currency", label: "通貨配分" },
  { href: "/dividend", label: "配当" },
];

export default function TopBar({ loadedAt, loading, onReload }) {
  const router = useRouter();
  const pathname = usePathname();

  return (
    <>
      <div className="topbar">
        <span className="logo">
          <span className="dim">&lt;</span> FORCE <span className="dim">&gt; CAPITAL</span>
        </span>
        <span className="spacer" />
        {loadedAt && (
          <span className="ts">{new Date(loadedAt).toLocaleString("ja-JP")} 取得</span>
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
