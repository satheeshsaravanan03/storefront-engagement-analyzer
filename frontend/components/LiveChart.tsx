'use client';

import { useEffect, useState } from 'react';
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
  BarChart, Bar, Legend,
} from 'recharts';
import { BarChart3 } from 'lucide-react';

interface FrameRow {
  timestamp: string;
  occupancy: number;
  total_in: number;
  total_out: number;
  fps: number;
  [key: string]: string | number;
}

const TOOLTIP_STYLE = {
  backgroundColor: '#18181C',
  border: '1px solid #2A2A32',
  borderRadius: '8px',
  color: '#E8E8F0',
  fontSize: '12px',
  fontFamily: 'var(--font-mono)',
};

export function LiveChart({ frameStatsUrl, inlineData }: {
  frameStatsUrl?: string;
  inlineData?: FrameRow[];
}) {
  const [data, setData] = useState<FrameRow[]>([]);
  const [tab, setTab] = useState<'occupancy' | 'flow' | 'fps'>('occupancy');

  useEffect(() => {
    if (inlineData) { setData(inlineData); return; }
    if (!frameStatsUrl) return;

    fetch(frameStatsUrl)
      .then(r => r.text())
      .then(csv => {
        const lines = csv.trim().split('\n');
        const headers = lines[0].split(',');
        const rows = lines.slice(1).map(line => {
          const vals = line.split(',');
          const obj: Record<string, string | number> = {};
          headers.forEach((h, i) => {
            const v = vals[i] ?? '';
            obj[h.trim()] = isNaN(Number(v)) ? v : Number(v);
          });
          return obj as FrameRow;
        });
        // Downsample to max 300 points for performance
        const step = Math.max(1, Math.floor(rows.length / 300));
        setData(rows.filter((_, i) => i % step === 0));
      })
      .catch(() => {});
  }, [frameStatsUrl, inlineData]);

  if (data.length === 0) return null;

  // Simplify timestamps to HH:MM:SS
  const chartData = data.map(d => ({
    ...d,
    t: typeof d.timestamp === 'string'
      ? d.timestamp.split('T')[1]?.substring(0, 8) ?? d.timestamp
      : String(d.timestamp),
  }));

  const tabs = [
    { key: 'occupancy', label: 'Occupancy' },
    { key: 'flow', label: 'IN / OUT' },
    { key: 'fps', label: 'FPS' },
  ] as const;

  return (
    <div className="glow-border bg-cv-card rounded-2xl p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <BarChart3 size={16} className="text-cv-accent" />
          <span className="font-semibold text-cv-text text-sm">Time-Series Analytics</span>
        </div>
        <div className="flex gap-1">
          {tabs.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-3 py-1 rounded-lg text-xs font-mono transition-colors ${
                tab === t.key
                  ? 'bg-cv-accent text-white'
                  : 'text-cv-sub hover:text-cv-text'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div style={{ height: 220 }}>
        {tab === 'occupancy' && (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="occGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#6C63FF" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#6C63FF" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="t" tick={{ fill: '#9090A8', fontSize: 10 }} interval="preserveStartEnd" />
              <YAxis tick={{ fill: '#9090A8', fontSize: 10 }} />
              <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={{ color: '#9090A8' }} />
              <Area type="monotone" dataKey="occupancy" stroke="#6C63FF" strokeWidth={2} fill="url(#occGrad)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        )}

        {tab === 'flow' && (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="inGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#22C55E" stopOpacity={0.25} />
                  <stop offset="95%" stopColor="#22C55E" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="outGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3B82F6" stopOpacity={0.25} />
                  <stop offset="95%" stopColor="#3B82F6" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="t" tick={{ fill: '#9090A8', fontSize: 10 }} interval="preserveStartEnd" />
              <YAxis tick={{ fill: '#9090A8', fontSize: 10 }} />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Legend wrapperStyle={{ color: '#9090A8', fontSize: 11 }} />
              <Area type="monotone" dataKey="total_in" stroke="#22C55E" strokeWidth={2} fill="url(#inGrad)" dot={false} name="Total IN" />
              <Area type="monotone" dataKey="total_out" stroke="#3B82F6" strokeWidth={2} fill="url(#outGrad)" dot={false} name="Total OUT" />
            </AreaChart>
          </ResponsiveContainer>
        )}

        {tab === 'fps' && (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="fpsGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#06B6D4" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#06B6D4" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="t" tick={{ fill: '#9090A8', fontSize: 10 }} interval="preserveStartEnd" />
              <YAxis tick={{ fill: '#9090A8', fontSize: 10 }} />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Area type="monotone" dataKey="fps" stroke="#06B6D4" strokeWidth={2} fill="url(#fpsGrad)" dot={false} name="FPS" />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
