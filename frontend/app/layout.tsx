import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { AppProviders } from "@/components/providers/app-providers";
import { connection } from "next/server";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Sistema de Orquestación — Banco Mercantil Santa Cruz",
  description: "Sistema de atención al cliente bancario inteligente",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  await connection();
  return (
    <html
      lang="es"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <a
          className="sr-only z-[100] rounded-lg bg-white px-4 py-2 text-[#071426] focus:not-sr-only focus:fixed focus:left-4 focus:top-4"
          href="#main-content"
        >
          Saltar al contenido principal
        </a>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
