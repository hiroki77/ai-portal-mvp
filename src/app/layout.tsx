import type { Metadata, Viewport } from "next";
import { Noto_Sans_JP } from "next/font/google";
import "./globals.css";

const notoSansJP = Noto_Sans_JP({
  variable: "--font-noto-sans-jp",
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "NapGO - 疲れたら、すぐナップ",
  description:
    "最短1時間からの仮眠サービス。タクシー手配からホテルチェックインまで、すべてワンタップで。",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ja" className={`${notoSansJP.variable} h-full`}>
      <body className="min-h-full flex flex-col">
        <div className="mx-auto w-full max-w-md flex flex-col min-h-screen">
          {children}
        </div>
      </body>
    </html>
  );
}
