'use client';

import { motion, AnimatePresence } from 'framer-motion';
import { AlertTriangle, AlertOctagon, Info, Bell } from 'lucide-react';
import clsx from 'clsx';

interface Alert {
  timestamp: string;
  zone: string;
  type: string;
  level: string;
  value: number;
  threshold: number;
}

const levelConfig = {
  CRITICAL: { icon: AlertOctagon, color: 'text-cv-red', bg: 'bg-cv-red/10', border: 'border-cv-red/30' },
  WARNING:  { icon: AlertTriangle, color: 'text-cv-amber', bg: 'bg-cv-amber/10', border: 'border-cv-amber/30' },
  INFO:     { icon: Info, color: 'text-cv-cyan', bg: 'bg-cv-cyan/10', border: 'border-cv-cyan/30' },
};

export function AlertBanner({ alerts }: { alerts: Alert[] }) {
  if (!alerts || alerts.length === 0) return null;

  return (
    <div className="glow-border bg-cv-card rounded-2xl p-5">
      <div className="flex items-center gap-2 mb-4">
        <Bell size={16} className="text-cv-amber" />
        <span className="font-semibold text-cv-text text-sm">Alert Log</span>
        <span className="bg-cv-amber/20 text-cv-amber text-xs font-mono px-2 py-0.5 rounded-full">
          {alerts.length}
        </span>
      </div>

      <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
        <AnimatePresence initial={false}>
          {alerts.map((alert, i) => {
            const level = (alert.level as keyof typeof levelConfig) in levelConfig
              ? alert.level as keyof typeof levelConfig
              : 'INFO';
            const { icon: Icon, color, bg, border } = levelConfig[level];
            const time = new Date(alert.timestamp).toLocaleTimeString();

            return (
              <motion.div
                key={i}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.05 }}
                className={clsx('flex items-start gap-3 p-3 rounded-xl border', bg, border)}
              >
                <Icon size={14} className={clsx(color, 'mt-0.5 flex-shrink-0')} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className={clsx('text-xs font-mono font-bold', color)}>{level}</span>
                    <span className="text-cv-sub text-xs font-mono">{time}</span>
                  </div>
                  <p className="text-cv-text text-xs">
                    <span className="font-semibold">{alert.zone}</span>
                    {' · '}{alert.type.replace(/_/g, ' ')}
                    {' · '}{alert.value}/{alert.threshold}
                  </p>
                </div>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </div>
  );
}
