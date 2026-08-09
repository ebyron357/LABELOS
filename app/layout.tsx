import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "LABELOS — Label Studio",
  description: "Design, preview, and manage print labels in one place.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
