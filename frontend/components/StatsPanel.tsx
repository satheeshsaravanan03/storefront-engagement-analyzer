'use client';

import { motion } from 'framer-motion';
import { Users, ArrowDownLeft, ArrowUpRight, Activity, Clock, Bell } from 'lucide-react';
import clsx from 'clsx';

interface StatsPanelProps {
  liveCount: number;
  countIn: number;
  countOut: number;
  occupancy: number;
  entryRate: number;
  avgDwell: number | null;
  zoneCounts: Record<string, number>;
  fps: number;
  isLive: boolean;
}

function StatCard({
  icon: Icon, label, value, sub, color, alert = false, delay = 0,
}: {
  icon: React.ElementType;
  label: string;
  value: string | number;
  sub?: string;
  color: string;
  alert?: boolean;
  delay?: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.4 }}
      className={clsx(
        'glow-border bg-cv-card rounded-xl p-4 relative overflow-hidden',
        alert && 'border-cv-red/50 alert-pulse'
      )}
    >
      {/* Background glow */}
      <div className={`absolute top-0 right-0 w-16 h-16 rounded-full blur-2xl opacity-10 ${color}`} />

      <div className="flex items-start justify-between mb-3">
        <p className="text-cv-sub text-xs font-mono uppercase tracking-wider">{label}</p>
        <div className={`w-7 h-7 rounded-lg ${color} bg-opacity-20 flex items-center justify-center`}>
          <Icon size={14} className={color.replace('bg-', 'text-')} />
        </div>
      </div>

      <p className={clsx(
        'font-display text-3xl stat-number',
        alert ? 'text-cv-red' : 'text-cv-text'
      )}>
        {typeof value === 'number' ? value.toLocaleString() : value}
      </p>

      {sub && <p className="text-cv-sub text-xs mt-1 font-mono">{sub}</p>}
    </motion.div>
  );
}

export function StatsPanel({
  liveCount, countIn, countOut, occupancy,
  entryRate, avgDwell, zoneCounts, fps, isLive,
}: StatsPanelProps) {
  const overcrowded = occupancy >= 10;

  return (
    <div className="space-y-3">
      {/* Live indicator */}
      {isLive && (
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 bg-cv-green rounded-full animate-pulse" />
          <span className="text-cv-green text-xs font-mono">LIVE · {fps.toFixed(1)} FPS</span>
        </div>
      )}

      {/* Main stats grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {isLive && (
          <StatCard
            icon={Users}
            label="Detected Now"
            value={liveCount}
            sub="persons in frame"
            color="bg-cv-accent"
            delay={0}
          />
        )}
        <StatCard
          icon={ArrowDownLeft}
          label="Total IN"
          value={countIn}
          color="bg-cv-green"
          delay={0.05}
        />
        <StatCard
          icon={ArrowUpRight}
          label="Total OUT"
          value={countOut}
          color="bg-blue-500"
          delay={0.1}
        />
        <StatCard
          icon={Users}
          label={isLive ? 'Occupancy' : 'Peak Occupancy'}
          value={occupancy}
          sub={overcrowded ? '⚠ ALERT' : `threshold: 10`}
          color="bg-cv-amber"
          alert={overcrowded}
          delay={0.15}
        />
        {isLive && (
          <StatCard
            icon={Activity}
            label="Entry Rate"
            value={`${entryRate.toFixed(2)}/s`}
            sub="per second"
            color="bg-cv-cyan"
            delay={0.2}
          />
        )}
        {avgDwell !== null && (
          <StatCard
            icon={Clock}
            label="Avg Wait Time"
            value={avgDwell !== null ? `${avgDwell.toFixed(1)}s` : '—'}
            sub={avgDwell !== null ? `${(avgDwell / 60).toFixed(2)} min` : 'no queue data'}
            color="bg-purple-500"
            delay={0.25}
          />
        )}
      </div>

      {/* Zone counts */}
      {Object.keys(zoneCounts).length > 0 && (
        <div className="glow-border bg-cv-card rounded-xl p-4">
          <p className="text-cv-sub text-xs font-mono mb-3">ZONE OCCUPANCY</p>
          <div className="space-y-2">
            {Object.entries(zoneCounts).map(([name, count]) => {
              const isQueue = name.toLowerCase().includes('queue');
              const threshold = isQueue ? 6 : 10;
              const pct = Math.min((count / threshold) * 100, 100);
              const over = count >= threshold;
              return (
                <div key={name}>
                  <div className="flex justify-between mb-1">
                    <span className="text-xs text-cv-sub font-mono">{name}</span>
                    <span className={clsx('text-xs font-mono font-bold', over ? 'text-cv-red' : 'text-cv-text')}>
                      {count} / {threshold}
                    </span>
                  </div>
                  <div className="h-1.5 bg-cv-border rounded-full overflow-hidden">
                    <motion.div
                      className={clsx('h-full rounded-full', over ? 'bg-cv-red' : isQueue ? 'bg-purple-500' : 'bg-cv-green')}
                      animate={{ width: `${pct}%` }}
                      transition={{ duration: 0.4 }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
