import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import { ThemeProvider } from '@/components/ThemeProvider';

const inter = Inter({ subsets: ['latin'], variable: '--font-inter' });

export const metadata: Metadata = {
  title: 'NusaRail Vision — Traffic Anomaly Detection',
  description:
    'Sistem Peringatan Dini Anomali Lalu Lintas Perlintasan Kereta Api · Real-time YOLOv8 Monitoring',
  keywords: ['traffic', 'anomaly', 'railway', 'yolov8', 'monitoring', 'NusaRail'],
  icons: {
    icon: '/Logo.ico',
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="id" className={inter.variable} suppressHydrationWarning>
      <body className="bg-white dark:bg-[#050d1a] antialiased text-slate-900 dark:text-slate-100 transition-colors duration-300">
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
