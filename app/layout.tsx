import "./globals.css";
import { GeistSans } from "geist/font/sans";
import { Toaster } from "sonner";
import { cn } from "@/lib/utils";
import { Navbar } from "@/components/navbar";

export const metadata = {
  title: "Snoqualmie Tourism Virtual Assistant",
  description:
    "The ultimate guide to Historic Downtown Snoqualmie.",
  openGraph: {
    images: [
      {
        url: "/og?title=Snoqualmie Tourism Virtual Assistant",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    images: [
      {
        url: "/og?title=Snoqualmie Tourism Virtual Assistant",
      },
    ],
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head></head>
      <body className={cn(GeistSans.className, "antialiased dark")}>
        <Toaster position="top-center" richColors />
        <Navbar />
        {children}
      </body>
    </html>
  );
}
