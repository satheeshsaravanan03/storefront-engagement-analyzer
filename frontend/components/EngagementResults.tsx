'use client';

import { Clock, Users, TrendingUp, Zap, FileText, Download } from 'lucide-react';
import clsx from 'clsx';
import type { Category, Visit } from '@/lib/api';

export function classify(dwell: number, engage: number, strong: number): Category {
  if (dwell >= strong) return 'strong';
  if (dwell >= engage) return 'potential';
  return 'not_flagged';
}

const LABEL: Record<Category, string> = {
  not_flagged: 'Not flagged',
  potential:   'Potential engagement',
  strong:      'Stronger signal',
};
const BADGE: Record<Category, string> = {
  not_flagged: 'bg-cv-border text-cv-sub',
  potential:   'bg-cv-amber/15 text-cv-amber',
  strong:      'bg-cv-green/15 text-cv-green',
};

export function summarize(visits: Visit[], engage: number, strong: number, durationSec: number) {
  const cls = visits.map(v => classify(v.dwell_sec, engage, strong));
  const potential = cls.filter(c => c === 'potential').length;
  const stronger  = cls.filter(c => c === 'strong').length;
  const dwells    = visits.map(v => v.dwell_sec);
  const avg = dwells.length ? dwells.reduce((a, b) => a + b, 0) / dwells.length : 0;
  const max = dwells.length ? Math.max(...dwells) : 0;
  return { total: visits.length, potential, stronger, notFlagged: visits.length - potential - stronger, avg, max, durationSec };
}

/* Counts, summary text and per-visit table. Visits are re-classified here
   from the raw dwell times, so changing the thresholds updates instantly. */
export function EngagementResults({ visits, engageSec, strongSec, durationSec, csvUrl }: {
  visits: Visit[];
  engageSec: number;
  strongSec: number;
  durationSec: number;
  csvUrl?: string;
}) {
  const s = summarize(visits, engageSec, strongSec, durationSec);

  const cards = [
    { icon: Users,      label: 'Tracked visits',          value: s.total,     color: 'text-cv-accent' },
    { icon: TrendingUp, label: 'Potential engagements',   value: s.potential, color: 'text-cv-amber'  },
    { icon: Zap,        label: 'Stronger signals',        value: s.stronger,  color: 'text-cv-green'  },
    { icon: Clock,      label: 'Avg / longest dwell',     value: `${s.avg.toFixed(1)}s / ${s.max.toFixed(1)}s`, color: 'text-cv-cyan' },
  ];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {cards.map(({ icon: Icon, label, value, color }) => (
          <div key={label} className="glow-border bg-cv-card rounded-2xl p-4">
            <Icon size={15} className={clsx(color, 'mb-2')} />
            <p className="font-display text-2xl text-cv-text">{value}</p>
            <p className="text-cv-sub text-xs font-mono mt-1">{label}</p>
          </div>
        ))}
      </div>

      <div className="glow-border bg-cv-card rounded-2xl p-5">
        <p className="text-cv-sub text-xs font-mono mb-2">SUMMARY</p>
        <p className="text-cv-text text-sm leading-relaxed">
          {s.total === 0
            ? `No one was tracked inside the storefront zone in ${s.durationSec.toFixed(0)}s of footage.`
            : `${s.total} tracked visit${s.total === 1 ? '' : 's'} in the storefront zone over ${s.durationSec.toFixed(0)}s of footage: ` +
              `${s.potential} potential engagement${s.potential === 1 ? '' : 's'} (${engageSec}–${strongSec}s) and ` +
              `${s.stronger} stronger signal${s.stronger === 1 ? '' : 's'} (${strongSec}s or more). ` +
              `${s.notFlagged} stayed under ${engageSec}s. Average dwell ${s.avg.toFixed(1)}s, longest ${s.max.toFixed(1)}s.`}
        </p>
        <p className="text-cv-sub text-xs mt-3 leading-relaxed">
          These results show potential engagement based on time spent near the storefront. Staying in the
          zone does not confirm a person looked at a product or intended to buy.
        </p>
      </div>

      <div className="glow-border bg-cv-card rounded-2xl overflow-hidden">
        <div className="px-5 py-3 border-b border-cv-border flex items-center gap-2">
          <FileText size={15} className="text-cv-cyan" />
          <span className="font-semibold text-cv-text text-sm">Visits</span>
          {csvUrl && (
            <a href={csvUrl} download
              className="ml-auto flex items-center gap-1.5 text-cv-accent hover:text-cv-accentL text-xs font-mono transition-colors">
              <Download size={12} /> visits.csv
            </a>
          )}
        </div>
        <div className="max-h-96 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-cv-card text-cv-sub text-xs font-mono">
              <tr className="border-b border-cv-border">
                <th className="text-left px-5 py-2 font-normal">Track ID</th>
                <th className="text-right px-3 py-2 font-normal">Entry</th>
                <th className="text-right px-3 py-2 font-normal">Exit</th>
                <th className="text-right px-3 py-2 font-normal">Dwell</th>
                <th className="text-left px-5 py-2 font-normal">Class</th>
              </tr>
            </thead>
            <tbody>
              {visits.map(v => {
                const c = classify(v.dwell_sec, engageSec, strongSec);
                return (
                  <tr key={v.track_id} className="border-b border-cv-border/50 text-cv-text">
                    <td className="px-5 py-2 font-mono">#{v.track_id}</td>
                    <td className="px-3 py-2 text-right font-mono">{v.entry_sec.toFixed(1)}s</td>
                    <td className="px-3 py-2 text-right font-mono">{v.exit_sec.toFixed(1)}s</td>
                    <td className="px-3 py-2 text-right font-mono font-bold">{v.dwell_sec.toFixed(1)}s</td>
                    <td className="px-5 py-2">
                      <span className={clsx('text-[11px] font-mono px-2 py-0.5 rounded', BADGE[c])}>{LABEL[c]}</span>
                    </td>
                  </tr>
                );
              })}
              {visits.length === 0 && (
                <tr><td colSpan={5} className="px-5 py-6 text-center text-cv-sub text-xs font-mono">No visits recorded</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
