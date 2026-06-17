import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Research Assistant — AI-Powered Multi-Agent Research",
  description:
    "Automate complex research synthesis with a multi-agent AI pipeline. Powered by GPT-4o, Gemini, and LangGraph.",
  keywords: ["AI research", "multi-agent", "LangGraph", "research automation"],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      </head>
      <body className="font-sans antialiased bg-bg-base text-slate-100 min-h-screen">
        {children}
      </body>
    </html>
  );
}
