'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Eye, Upload, List, Loader2, Contact } from 'lucide-react';
import clsx from 'clsx';
import { checkBackendHealth } from '@/lib/api';

const NAV = [
  { href: '/dashboard', label: 'Upload & Analyse', icon: Upload },
  { href: '/jobs',      label: 'Jobs',             icon: List },
  { href: '/identity',  label: 'Identity',         icon: Contact },
];

function BackendStatus() {
  const [online, setOnline] = useState<boolean | null>(null);
  useEffect(() => {
    const check = () => checkBackendHealth().then(setOnline);
    check();
    const t = setInterval(check, 15000);
    return () => clearInterval(t);
  }, []);
  return (
    <div className={clsx(
      'flex items-center gap-2.5 text-sm font-medium px-3 py-2.5 rounded-xl border',
      online === null ? 'border-cv-border text-cv-sub' :
      online          ? 'border-cv-green/30 text-cv-green bg-cv-green/5' :
                        'border-cv-red/30 text-cv-red bg-cv-red/5',
    )}>
      {online === null ? <Loader2 size={12} className="animate-spin" /> :
       <span className={clsx('w-2 h-2 rounded-full', online ? 'bg-cv-green' : 'bg-cv-red')} />}
      {online === null ? 'Checking...' : online ? 'Backend online' : 'Backend offline'}
    </div>
  );
}

/* Left sidebar on desktop, compact top bar on small screens. */
export function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const Logo = (
    <div className="flex items-center gap-2.5">
      <div className="w-8 h-8 bg-gradient-to-br from-cv-accent to-cv-cyan rounded-lg flex items-center justify-center">
        <Eye size={15} className="text-white" />
      </div>
      <span className="font-display text-lg text-cv-text leading-tight">Storefront<br className="hidden md:block" /> Engagement</span>
    </div>
  );

  return (
    <div className="noise mesh-bg min-h-screen">
      {/* Desktop sidebar */}
      <aside className="hidden md:flex fixed inset-y-0 left-0 w-60 flex-col bg-cv-surface border-r border-cv-border px-4 pt-5 pb-16 z-30">
        <div className="px-2 mb-8">{Logo}</div>
        <p className="px-3 mb-2 text-[11px] font-semibold tracking-wider text-cv-sub">WORKSPACE</p>
        <nav className="space-y-1 flex-1">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = path === href || path.startsWith(href + '/');
            return (
              <Link key={href} href={href}
                className={clsx(
                  'flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors',
                  active ? 'bg-cv-accent/10 text-cv-accent font-semibold' : 'text-cv-sub hover:bg-cv-black hover:text-cv-text',
                )}>
                <Icon size={16} /> {label}
              </Link>
            );
          })}
        </nav>
        <BackendStatus />
      </aside>

      {/* Mobile top bar */}
      <header className="md:hidden sticky top-0 z-30 bg-cv-surface border-b border-cv-border px-4 py-3 flex items-center justify-between">
        {Logo}
        <nav className="flex gap-1">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = path === href || path.startsWith(href + '/');
            return (
              <Link key={href} href={href} aria-label={label}
                className={clsx('p-2 rounded-lg', active ? 'bg-cv-accent/10 text-cv-accent' : 'text-cv-sub')}>
                <Icon size={18} />
              </Link>
            );
          })}
        </nav>
      </header>

      <main className="md:pl-60">
        <div className="max-w-6xl mx-auto px-6 py-8">{children}</div>
      </main>
    </div>
  );
}
