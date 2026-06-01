import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "./auth/AuthContext";
import { ToastProvider } from "./components/Toast";

export const metadata: Metadata = {
  title: "HR AI Command Center",
  description: "Multi-agent control plane for HR operations.",
};

/**
 * Root layout. Loads the Inter font and the global brand styles, then renders
 * the active page inside a full-height shell.
 */
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-screen">
        <AuthProvider>
          <ToastProvider>{children}</ToastProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
