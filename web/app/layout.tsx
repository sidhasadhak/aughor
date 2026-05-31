import type { Metadata } from "next";
import localFont from "next/font/local";
import { IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

const dmSans = localFont({
  src: [
    {
      path: "../public/fonts/DMSans-VariableFont_opsz,wght.ttf",
      style: "normal",
    },
    {
      path: "../public/fonts/DMSans-Italic-VariableFont_opsz,wght.ttf",
      style: "italic",
    },
  ],
  variable: "--font-dm-sans",
  display: "swap",
});

const ibmPlexMono = IBM_Plex_Mono({
  variable: "--font-ibm-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
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
      className={`${dmSans.variable} ${ibmPlexMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
