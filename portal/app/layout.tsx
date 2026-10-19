import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Ownly",
  description: "Find a home, list your property, and connect directly on Ownly.",
  icons: {
    icon: "/assets/favicon.svg",
    shortcut: "/assets/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
