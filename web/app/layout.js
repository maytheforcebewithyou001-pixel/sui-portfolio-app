import "./globals.css";

export const metadata = {
  title: "FORCE CAPITAL",
  description: "個人投資家向けポートフォリオ管理",
};

export default function RootLayout({ children }) {
  return (
    <html lang="ja">
      <body>{children}</body>
    </html>
  );
}
