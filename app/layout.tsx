import type { Metadata } from "next";
import "./globals.css";
import "./discovery.css";
import "./marketplace.css";
export const metadata: Metadata = { title: "DealFeed — Good work starts here", description: "Discover catering, event decorations, website development, and keynote speaking projects, request something similar, and get a proposal from the people who made it." };
export default function RootLayout({ children }: Readonly<{children: React.ReactNode}>) { return <html lang="en"><body>{children}</body></html>; }
