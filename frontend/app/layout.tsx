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
  title: 'CrowdVision — Real-Time People Counting & Queue Intelligence',
  description:
    'Upload any CCTV video and get AI-powered people counting, queue length estimation, dwell time analytics, and overcrowding alerts — in seconds.',
  keywords: ['people counting', 'queue management', 'crowd analytics', 'retail AI', 'YOLOv8'],
  openGraph: {
    title: 'CrowdVision',
    description: 'AI-powered crowd intelligence for retail, events & healthcare.',
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
