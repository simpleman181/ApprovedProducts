import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CDSCO approvals and SEC recommendations",
  description: "Search CDSCO approvals and Subject Expert Committee recommendations with a link back to the source.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;500;600&family=Newsreader:opsz,wght@6..72,500;6..72,600&display=swap"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
