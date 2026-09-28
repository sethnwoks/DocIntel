import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import "./globals.css";

// Plex Sans carries the UI and body text; Plex Mono is reserved for technical
// metadata (citations, chunk ids, scores). Syne was previously set as the body
// face - it is a display typeface and is hard to read at UI sizes.
const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-sans",
});

const ibmMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "DocIntel · Hybrid RAG",
  description: "Multitenant document intelligence with layout-aware RAG",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" data-theme="dark">
      <body className={`${plexSans.variable} ${ibmMono.variable}`}>
        {children}
      </body>
    </html>
  );
}
