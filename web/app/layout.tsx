import type { Metadata } from "next";
import { ReactNode } from "react";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import { AppProvider } from "@/lib/app-context";
import Shell from "@/components/Shell";

export const metadata: Metadata = {
  title: "GST CashPilot",
  description: "Know your GST cash before you file. Draft only, nothing is filed.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="font-sans antialiased">
        <AuthProvider><AppProvider><Shell>{children}</Shell></AppProvider></AuthProvider>
      </body>
    </html>
  );
}
