import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./app.css";

export const metadata: Metadata = {
  title: "AI-native M&A",
  description: "Sourced answers, buyer screening and KPIs for a sell-side deal team",
};

// ui.css is the design system, served unchanged from public/ (see design/DESIGN.md); app.css holds
// the few compositions this project needs, built from its tokens only.
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        {/* eslint-disable-next-line @next/next/no-css-tags */}
        <link rel="stylesheet" href="/ui.css" />
      </head>
      <body>{children}</body>
    </html>
  );
}
