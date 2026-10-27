import type { Metadata } from 'next';
import { DM_Serif_Display, DM_Sans, DM_Mono } from 'next/font/google';
import './globals.css';

const display = DM_Serif_Display({
  subsets: ['latin'],
  weight: ['400'],
  variable: '--font-display',
  display: 'swap',
});

const body = DM_Sans({
  subsets: ['latin'],
  weight: ['300', '400', '500', '600'],
  variable: '--font-body',
  display: 'swap',
});

const mono = DM_Mono({
  subsets: ['latin'],
  weight: ['300', '400', '500'],
  variable: '--font-mono',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'Storefront Engagement Analyzer',
  description:
    'Upload a prerecorded storefront video and measure how long people stay in front of the shop, with configurable engagement thresholds.',
  keywords: ['storefront analytics', 'dwell time', 'visitor engagement', 'retail AI', 'YOLOv8'],
  openGraph: {
    title: 'Storefront Engagement Analyzer',
    description: 'Dwell-time based potential engagement analysis for retail storefronts.',
    type: 'website',
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <body className="bg-cv-black text-cv-text font-body antialiased">
        {children}
      </body>
    </html>
  );
}
