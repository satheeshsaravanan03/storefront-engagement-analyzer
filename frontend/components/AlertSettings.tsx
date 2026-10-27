'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Bell, Mail, Eye, EyeOff, CheckCircle2, AlertTriangle, X, ExternalLink } from 'lucide-react';
import clsx from 'clsx';

export interface AlertConfig {
  email_enabled: boolean;
  email_from: string;
  email_password: string;
  email_to: string;
  sustained_sec: number;
}

interface Props {
  config: AlertConfig;
  onChange: (cfg: AlertConfig) => void;
  onClose: () => void;
}

export function AlertSettings({ config, onChange, onClose }: Props) {
  const [showPass, setShowPass]   = useState(false);
  const [testing, setTesting]     = useState(false);
  const [testResult, setTestResult] = useState<'ok' | 'fail' | null>(null);

  const update = (k: keyof AlertConfig, v: string | boolean | number) =>
    onChange({ ...config, [k]: v });

  const testEmail = async () => {
    if (!config.email_from || !config.email_password || !config.email_to) return;
    setTesting(true);
    setTestResult(null);
    try {
      const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';
      const res = await fetch(`${BACKEND}/api/test-email`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email_from:     config.email_from,
          email_password: config.email_password,
          email_to:       config.email_to,
        }),
      });
      setTestResult(res.ok ? 'ok' : 'fail');
    } catch {
      setTestResult('fail');
    } finally {
      setTesting(false);
    }
  };

  const allFilled = config.email_from && config.email_password && config.email_to;

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      className="glow-border bg-cv-card rounded-2xl p-6 space-y-5"
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bell size={15} className="text-cv-accent" />
          <span className="font-semibold text-cv-text text-sm">Email Alert Settings</span>
        </div>
        <button onClick={onClose} className="text-cv-sub hover:text-cv-text transition-colors">
          <X size={15} />
        </button>
      </div>

      {/* Enable toggle */}
      <div className="flex items-center justify-between bg-cv-surface border border-cv-border rounded-xl px-4 py-3">
        <div>
          <p className="text-cv-text text-sm font-medium">Enable email alerts</p>
          <p className="text-cv-sub text-xs mt-0.5">
            {config.sustained_sec === 0 ? 'Email fires immediately on threshold breach' : `Email fires after ${config.sustained_sec}s sustained overcrowding`}
          </p>
        </div>
        <button
          onClick={() => update('email_enabled', !config.email_enabled)}
          className={clsx(
            'w-11 h-6 rounded-full transition-colors duration-200 relative flex-shrink-0',
            config.email_enabled ? 'bg-cv-accent' : 'bg-cv-border'
          )}
        >
          <span className={clsx(
            'absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-all duration-200',
            config.email_enabled ? 'left-5.5' : 'left-0.5'
          )} style={{ left: config.email_enabled ? '22px' : '2px' }} />
        </button>
      </div>

      {/* Sustained alert duration */}
      <div className="bg-cv-surface border border-cv-border rounded-xl px-4 py-4">
        <div className="flex items-center justify-between mb-3">
          <div>
            <p className="text-cv-text text-sm font-medium">Alert after sustained crowding</p>
            <p className="text-cv-sub text-xs mt-0.5">
              {config.sustained_sec === 0
                ? 'Email fires immediately on first detection'
                : `Email fires after ${config.sustained_sec}s of continuous overcrowding`}
            </p>
          </div>
          <span className="text-cv-accent font-mono font-bold text-lg min-w-[48px] text-right">
            {config.sustained_sec}s
          </span>
        </div>

        {/* Quick select buttons */}
        <div className="flex gap-2 mb-3 flex-wrap">
          {[0, 10, 15, 20, 30, 45, 60].map(sec => (
            <button
              key={sec}
              onClick={() => update('sustained_sec', sec)}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono font-semibold transition-all ${
                config.sustained_sec === sec
                  ? 'bg-cv-accent text-white'
                  : 'bg-cv-card border border-cv-border text-cv-sub hover:text-cv-text hover:border-cv-accent/40'
              }`}
            >
              {sec === 0 ? 'Instant' : `${sec}s`}
            </button>
          ))}
        </div>

        {/* Fine-tune slider */}
        <input
          type="range"
          min={5} max={120} step={5}
          value={config.sustained_sec}
          onChange={e => update('sustained_sec', parseInt(e.target.value))}
          className="w-full h-1.5 bg-cv-border rounded-full appearance-none cursor-pointer accent-cv-accent"
        />
        <div className="flex justify-between text-[10px] text-cv-sub font-mono mt-1">
          <span>5s (instant)</span>
          <span>60s (1 min)</span>
          <span>120s (2 min)</span>
        </div>
      </div>

      {/* Gmail App Password guide */}
      <div className="bg-cv-amber/5 border border-cv-amber/20 rounded-xl px-4 py-3">
        <p className="text-cv-amber text-xs font-semibold mb-1">
          ⚠ Use Gmail App Password — not your regular password
        </p>
        <p className="text-cv-sub text-xs leading-relaxed">
          Google Account → Security → 2-Step Verification → App passwords → Generate
        </p>
        <a
          href="https://myaccount.google.com/apppasswords"
          target="_blank" rel="noopener noreferrer"
          className="flex items-center gap-1 text-cv-accent text-xs mt-2 hover:underline"
        >
          <ExternalLink size={11} /> Open App Passwords page
        </a>
      </div>

      {/* Email from */}
      <div>
        <label className="text-cv-sub text-xs font-mono mb-1.5 block">
          YOUR GMAIL (sends from)
        </label>
        <input
          type="email"
          value={config.email_from}
          onChange={e => update('email_from', e.target.value)}
          placeholder="yourname@gmail.com"
          className="w-full bg-cv-surface border border-cv-border rounded-xl px-4 py-2.5
            text-cv-text text-sm placeholder:text-cv-muted focus:border-cv-accent
            focus:outline-none transition-colors"
        />
      </div>

      {/* App password */}
      <div>
        <label className="text-cv-sub text-xs font-mono mb-1.5 block">
          GMAIL APP PASSWORD (16 characters)
        </label>
        <div className="relative">
          <input
            type={showPass ? 'text' : 'password'}
            value={config.email_password}
            onChange={e => update('email_password', e.target.value)}
            placeholder="xxxx xxxx xxxx xxxx"
            className="w-full bg-cv-surface border border-cv-border rounded-xl px-4 py-2.5
              text-cv-text text-sm placeholder:text-cv-muted focus:border-cv-accent
              focus:outline-none transition-colors pr-12"
          />
          <button
            type="button"
            onClick={() => setShowPass(!showPass)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-cv-sub hover:text-cv-text transition-colors"
          >
            {showPass ? <EyeOff size={15} /> : <Eye size={15} />}
          </button>
        </div>
      </div>

      {/* Alert recipient */}
      <div>
        <label className="text-cv-sub text-xs font-mono mb-1.5 block">
          ALERT RECIPIENT EMAIL (receives alerts)
        </label>
        <input
          type="email"
          value={config.email_to}
          onChange={e => update('email_to', e.target.value)}
          placeholder="manager@company.com"
          className="w-full bg-cv-surface border border-cv-border rounded-xl px-4 py-2.5
            text-cv-text text-sm placeholder:text-cv-muted focus:border-cv-accent
            focus:outline-none transition-colors"
        />
        <p className="text-cv-sub text-[11px] font-mono mt-1">
          Can be the same as your Gmail — sends to yourself
        </p>
      </div>

      {/* Alert triggers info */}
      <div className="bg-cv-surface border border-cv-border rounded-xl px-4 py-3">
        <p className="text-cv-sub text-xs font-mono mb-2">EMAIL FIRES WHEN:</p>
        <div className="space-y-1.5">
          {[
            config.sustained_sec === 0
              ? 'Queue zone > threshold — email fires immediately'
              : `Queue zone > threshold for ${config.sustained_sec} continuous seconds`,
            config.sustained_sec === 0
              ? 'General floor overcrowded — email fires immediately'
              : `General floor overcrowded for ${config.sustained_sec} continuous seconds`,
            'Entry rate spike > 2.5 persons/sec',
          ].map(t => (
            <div key={t} className="flex items-start gap-2">
              <Mail size={11} className="text-cv-accent mt-0.5 flex-shrink-0" />
              <span className="text-cv-sub text-xs">{t}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Test + save buttons */}
      <div className="flex gap-3">
        <button
          onClick={testEmail}
          disabled={!allFilled || testing}
          className={clsx(
            'flex-1 py-2.5 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 transition-all',
            allFilled && !testing
              ? 'glow-border text-cv-text hover:border-cv-accent/50'
              : 'opacity-40 cursor-not-allowed glow-border text-cv-sub'
          )}
        >
          {testing ? (
            <><span className="animate-spin">⟳</span> Sending test...</>
          ) : (
            <><Mail size={14} /> Send Test Email</>
          )}
        </button>
      </div>

      {/* Test result */}
      <AnimatePresence>
        {testResult && (
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className={clsx(
              'flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm',
              testResult === 'ok'
                ? 'bg-cv-green/10 border border-cv-green/30 text-cv-green'
                : 'bg-cv-red/10 border border-cv-red/30 text-cv-red'
            )}
          >
            {testResult === 'ok'
              ? <><CheckCircle2 size={15} /> Test email sent! Check your inbox.</>
              : <><AlertTriangle size={15} /> Failed. Check credentials or App Password.</>
            }
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}