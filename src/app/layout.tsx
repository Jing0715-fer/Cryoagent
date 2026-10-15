import type { Metadata, Viewport } from "next";
import { Geist, Instrument_Serif, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const instrumentSerif = Instrument_Serif({
  variable: "--font-instrument-serif",
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "CryoAgent Pro — 蛋白质结构智能分析平台",
  description:
    "基于 AI 的 Cryo-EM 文献与蛋白质结构智能分析系统：混合检索、Agent 工具调用、3D 结构可视化、序列深度分析。重构自 Flask 版 Cryoagent。",
  keywords: ["Cryo-EM", "蛋白质结构", "PDB", "RAG", "知识图谱", "序列比对", "结构生物学"],
  icons: { icon: "/logo.svg" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${instrumentSerif.variable} ${plexMono.variable} antialiased bg-background text-foreground`}
      >
        {children}
      </body>
    </html>
  );
}
