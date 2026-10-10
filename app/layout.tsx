import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "DealFeed — Good work starts here", description: "Discover completed website projects, request something similar, and get a proposal from the people who made it." };
export default function RootLayout({ children }: Readonly<{children: React.ReactNode}>) { return <html lang="en"><body>{children}</body></html>; }
