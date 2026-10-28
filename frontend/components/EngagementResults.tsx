'use client';

import { Clock, Users, TrendingUp, Zap, FileText, Download } from 'lucide-react';
import clsx from 'clsx';
import type { Behaviour, Viewer } from '@/lib/api';

export function classify(attention: number, glance: number, engage: number, strong: number): Behaviour {
  if (attention >= strong) return 'strong';
  if (attention >= engage) return 'engaged';
  if (attention >= glance) return 'looked';
  return 'glanced';
}

const LABEL: Record<Behaviour, string> = {
  glanced: 'Glanced',
  looked:  'Stopped & looked',
  engaged: 'Engaged',
  strong:  'Strongly engaged',
};
const BADGE: Record<Behaviour, string> = {
  glanced: 'bg-cv-border text-cv-sub',
  looked:  'bg-cv-cyan/15 text-cv-cyan',
  engaged: 'bg-cv-amber/15 text-cv-amber',
  strong:  'bg-cv-green/15 text-cv-green',
};

export function summarize(viewers: Viewer[], glance: number, engage: number, strong: number) {
  const cls = viewers.map(v => classify(v.attention_sec, glance, engage, strong));
  const count = (b: Behaviour) => cls.filter(c => c === b).length;
  const att = viewers.map(v => v.attention_sec);
  const avg = att.length ? att.reduce((a, b) => a + b, 0) / att.length : 0;
  const max = att.length ? Math.max(...att) : 0;
  return {
    total: viewers.length,
    glanced: count('glanced'), looked: count('looked'),
    engaged: count('engaged'), strong: count('strong'),
    avg, max,
  };
}

/* Counts, summary text and per-viewer table. Viewers are re-classified here
   from the raw attention times, so changing the thresholds updates instantly. */
export function EngagementResults({ viewers, glanceSec, engageSec, strongSec, durationSec, ignored, csvUrl }: {
  viewers: Viewer[];
  glanceSec: number;
  engageSec: number;
  strongSec: number;
  durationSec: number;
  ignored: number;
  csvUrl?: string;
}) {
  const s = summarize(viewers, glanceSec, engageSec, strongSec);
  const interested = s.engaged + s.strong;

  const cards = [
    { icon: Users,      label: 'Viewers (looked at display)', value: s.total,    color: 'text-cv-accent' },
    { icon: TrendingUp, label: 'Engaged or more',             value: interested, color: 'text-cv-amber'  },
    { icon: Zap,        label: 'Strongly engaged',            value: s.strong,   color: 'text-cv-green'  },
    { icon: Clock,      label: 'Avg / longest attention',     value: `${s.avg.toFixed(1)}s / ${s.max.toFixed(1)}s`, color: 'text-cv-cyan' },
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
            ? `No one was seen looking at the display in ${durationSec.toFixed(0)}s of footage.`
            : `${s.total} viewer${s.total === 1 ? '' : 's'} looked at the display over ${durationSec.toFixed(0)}s of footage: ` +
              `${s.glanced} glanced (under ${glanceSec}s), ${s.looked} stopped and looked (${glanceSec}–${engageSec}s), ` +
              `${s.engaged} engaged (${engageSec}–${strongSec}s) and ${s.strong} strongly engaged (${strongSec}s or more). ` +
              `Average attention ${s.avg.toFixed(1)}s, longest ${s.max.toFixed(1)}s.`}
        </p>
        <p className="text-cv-sub text-xs mt-3 leading-relaxed">
          {ignored} other {ignored === 1 ? 'person was' : 'people were'} near the camera but never looked long enough to count.
          People far away or just passing are not counted. Attention is measured from head direction, not eye
          gaze, and does not confirm purchase intent. Each ID is a temporary tracker ID: a person who leaves the
          video and comes back may be counted again.
        </p>
      </div>

      <div className="glow-border bg-cv-card rounded-2xl overflow-hidden">
        <div className="px-5 py-3 border-b border-cv-border flex items-center gap-2">
          <FileText size={15} className="text-cv-cyan" />
          <span className="font-semibold text-cv-text text-sm">Viewers</span>
          {csvUrl && (
            <a href={csvUrl} download
              className="ml-auto flex items-center gap-1.5 text-cv-accent hover:text-cv-accentL text-xs font-mono transition-colors">
              <Download size={12} /> viewers.csv
            </a>
          )}
        </div>
        <div className="max-h-96 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-cv-card text-cv-sub text-xs font-mono">
              <tr className="border-b border-cv-border">
                <th className="text-left px-5 py-2 font-normal">ID</th>
                <th className="text-right px-3 py-2 font-normal">First seen</th>
                <th className="text-right px-3 py-2 font-normal">Near camera</th>
                <th className="text-right px-3 py-2 font-normal">Attention</th>
                <th className="text-right px-3 py-2 font-normal">Looks</th>
                <th className="text-left px-5 py-2 font-normal">Behaviour</th>
              </tr>
            </thead>
            <tbody>
              {viewers.map(v => {
                const c = classify(v.attention_sec, glanceSec, engageSec, strongSec);
                return (
                  <tr key={v.person_id} className="border-b border-cv-border/50 text-cv-text">
                    <td className="px-5 py-2 font-mono">#{v.person_id}</td>
                    <td className="px-3 py-2 text-right font-mono">{v.first_sec.toFixed(1)}s</td>
                    <td className="px-3 py-2 text-right font-mono">{v.present_sec.toFixed(1)}s</td>
                    <td className="px-3 py-2 text-right font-mono font-bold">{v.attention_sec.toFixed(1)}s</td>
                    <td className="px-3 py-2 text-right font-mono">{v.looks}</td>
                    <td className="px-5 py-2">
                      <span className={clsx('text-[11px] font-mono px-2 py-0.5 rounded', BADGE[c])}>{LABEL[c]}</span>
                    </td>
                  </tr>
                );
              })}
              {viewers.length === 0 && (
                <tr><td colSpan={6} className="px-5 py-6 text-center text-cv-sub text-xs font-mono">No viewers recorded</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
