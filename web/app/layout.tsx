import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { Toaster } from "@/components/ui/toast";
import { Providers } from "./providers";
import { NAV_COLLAPSE_BOOT } from "@/lib/navCollapse";
import "./globals.css";

// Two families, both self-hosted by next/font at build time (no runtime request
// to a font CDN, so nothing here depends on the network at page load).
// Inter carries the UI; JetBrains Mono carries every figure, id, timestamp and
// metric — a tabular face so a column of numbers lines up on the decimal.
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

/**
 * Absolute base for the relative URLs in `metadata` below. The OG image is `/aughor-logo.jpeg`
 * — a relative path a crawler cannot fetch — so Next resolves it against this. Left unset, Next
 * warns at build time and falls back to `http://localhost:3000`, which would ship a localhost
 * image URL in the OG tags of every real deployment.
 *
 * Precedence, most specific first:
 *   1. NEXT_PUBLIC_SITE_URL — an explicit public origin, for any deployment that has one
 *   2. Vercel's own production domain — the stable one; VERCEL_URL is per-deployment, so a
 *      preview build would otherwise stamp its throwaway hostname into the tags
 *   3. http://localhost:3000 — the local development default, same value Next was guessing
 */
const siteUrl =
  process.env.NEXT_PUBLIC_SITE_URL ||
  (process.env.VERCEL_PROJECT_PRODUCTION_URL
    ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}`
    : "http://localhost:3000");

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: "Aughor — Autonomous Intelligence Platform",
  description: "Aughor is an Autonomous Intelligence Platform — continuously explores your data, builds a living business ontology, and answers complex analytical questions with evidence.",
  icons: {
    icon: "/aughor-logo.jpeg",
    apple: "/aughor-logo.jpeg",
  },
  openGraph: {
    title: "Aughor — Autonomous Intelligence Platform",
    description: "Your warehouse, always thinking.",
    images: [{ url: "/aughor-logo.jpeg", width: 1024, height: 1024, alt: "Aughor" }],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${jetbrainsMono.variable} h-full antialiased`}
      // NAV_COLLAPSE_BOOT sets data-nav on <html> before React hydrates (an attribute React does not
      // render), so a collapsed rail is drawn collapsed from the first paint, with no hydration warning.
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: NAV_COLLAPSE_BOOT }} />
      </head>
      <body className="min-h-full flex flex-col">
        <Providers>
          {children}
          <Toaster />
        </Providers>
      </body>
    </html>
  );
}
