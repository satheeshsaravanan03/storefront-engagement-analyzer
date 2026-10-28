'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Eye, ChevronRight, Loader2, Trash2, X, Download, RefreshCw, Upload, Film, AlertTriangle,
} from 'lucide-react';
import clsx from 'clsx';
import { listJobs, deleteJob, getJobStatus, type JobSummary, type AnalysisResult } from '@/lib/api';
import { EngagementResults } from '@/components/EngagementResults';

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

const STATUS_BADGE: Record<JobSummary['status'], string> = {
  queued:     'bg-cv-border text-cv-sub',
  processing: 'bg-cv-cyan/15 text-cv-cyan',
  done:       'bg-cv-green/15 text-cv-green',
  error:      'bg-cv-red/15 text-cv-red',
};

/* ── Side drawer: viewers of one job ──────────────────────── */
function JobDrawer({ job, onClose }: { job: JobSummary; onClose: () => void }) {
  const [detail, setDetail] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDetail(null); setError(null);
    getJobStatus(job.job_id)
      .then(setDetail)
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load job'));
  }, [job.job_id]);

  // Thresholds this job was processed with (read-only)
  const thr = {
    glance: detail?.stats?.glance_sec ?? 2,
    engage: detail?.stats?.engage_sec ?? 5,
    strong: detail?.stats?.strong_sec ?? 10,
  };

  return (
    <>
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        onClick={onClose} className="fixed inset-0 bg-black/50 z-40" />
      <motion.aside
        initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }}
        transition={{ type: 'tween', duration: 0.25 }}
        className="fixed top-0 right-0 h-full w-full max-w-3xl bg-cv-surface border-l border-cv-border z-50 overflow-y-auto"
      >
        <div className="sticky top-0 bg-cv-surface/95 backdrop-blur border-b border-cv-border px-6 py-4 flex items-center gap-3 z-10">
          <div className="min-w-0">
            <p className="font-semibold text-cv-text truncate">{job.filename}</p>
            <p className="text-cv-sub text-xs font-mono">Job {job.job_id} · {new Date(job.created_at * 1000).toLocaleString()}</p>
          </div>
          <div className="ml-auto flex items-center gap-3">
            {job.status === 'done' && (
              <a href={`${BACKEND}/api/download/${job.job_id}/zip`}
                className="flex items-center gap-1.5 bg-cv-accent hover:bg-cv-accentL text-white text-xs font-semibold px-3 py-2 rounded-xl transition-colors">
                <Download size={13} /> ZIP
              </a>
            )}
            <button onClick={onClose} className="text-cv-sub hover:text-cv-text transition-colors"><X size={18} /></button>
          </div>
        </div>

        <div className="p-6 space-y-4">
          {!detail && !error && (
            <div className="flex items-center gap-2 text-cv-sub text-sm"><Loader2 size={14} className="animate-spin" /> Loading viewers...</div>
          )}
          {error && <p className="text-cv-red text-sm font-mono">{error}</p>}
          {detail?.status === 'error' && (
            <div className="glow-border bg-cv-red/5 border-cv-red/30 rounded-2xl p-4 flex gap-3">
              <AlertTriangle size={18} className="text-cv-red flex-shrink-0" />
              <p className="text-cv-sub text-xs font-mono whitespace-pre-wrap">{detail.error}</p>
            </div>
          )}
          {detail?.status === 'done' && (
            <>
              <div className="glow-border bg-cv-card rounded-2xl p-4 flex items-center gap-6 flex-wrap text-sm text-cv-sub">
                <span className="text-xs font-mono">THRESHOLDS USED</span>
                <span>Looked from <span className="font-mono text-cv-text">{thr.glance} s</span></span>
                <span>Engaged from <span className="font-mono text-cv-text">{thr.engage} s</span></span>
                <span>Strong from <span className="font-mono text-cv-text">{thr.strong} s</span></span>
              </div>
              <EngagementResults
                viewers={detail.viewers ?? []}
                glanceSec={thr.glance} engageSec={thr.engage} strongSec={thr.strong}
                durationSec={detail.stats?.duration_sec ?? 0}
                ignored={detail.stats?.ignored ?? 0}
                csvUrl={detail.viewers_url}
                jsonUrl={detail.engaged_json_url}
                imageBase={`${BACKEND}/api/file/${job.job_id}/`}
              />
            </>
          )}
        </div>
      </motion.aside>
    </>
  );
}

/* ── Jobs page ────────────────────────────────────────────── */
export default function JobsPage() {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<JobSummary | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(() => {
    listJobs().then(j => { setJobs(j); setError(null); })
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load jobs'));
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  // Keep running jobs fresh
  useEffect(() => {
    if (!jobs?.some(j => j.status === 'queued' || j.status === 'processing')) return;
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [jobs, refresh]);

  const handleDelete = async (j: JobSummary) => {
    if (!window.confirm(`Delete job ${j.job_id} (${j.filename}) and all its files?`)) return;
    setBusy(j.job_id);
    try {
      await deleteJob(j.job_id);
      if (selected?.job_id === j.job_id) setSelected(null);
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Delete failed');
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="noise mesh-bg min-h-screen">
      <nav className="border-b border-cv-border bg-cv-surface/80 backdrop-blur-xl px-6 py-4 flex items-center justify-between sticky top-0 z-30">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 bg-gradient-to-br from-cv-accent to-cv-cyan rounded-lg flex items-center justify-center">
            <Eye size={13} className="text-white" />
          </div>
          <span className="font-display text-lg text-cv-text">Storefront Engagement</span>
          <ChevronRight size={14} className="text-cv-border" />
          <span className="text-cv-sub text-sm">Jobs</span>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={refresh}
            className="glow-border bg-cv-card text-cv-sub hover:text-cv-text px-3 py-1.5 rounded-xl text-sm flex items-center gap-2 transition-colors">
            <RefreshCw size={14} /> Refresh
          </button>
          <Link href="/dashboard"
            className="bg-cv-accent hover:bg-cv-accentL text-white px-3 py-1.5 rounded-xl text-sm flex items-center gap-2 transition-colors">
            <Upload size={14} /> New Video
          </Link>
        </div>
      </nav>

      <div className="max-w-6xl mx-auto px-6 py-8">
        <h1 className="font-display text-4xl text-cv-text mb-2">Uploaded Videos</h1>
        <p className="text-cv-sub mb-6">One record per analysed video. Click a row to see its viewers.</p>

        {error && <p className="text-cv-red text-sm font-mono mb-4">{error}</p>}

        <div className="glow-border bg-cv-card rounded-2xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="text-cv-sub text-xs font-mono">
              <tr className="border-b border-cv-border">
                <th className="text-left px-5 py-3 font-normal">Job ID</th>
                <th className="text-left px-3 py-3 font-normal">Video</th>
                <th className="text-left px-3 py-3 font-normal">Uploaded</th>
                <th className="text-left px-3 py-3 font-normal">Status</th>
                <th className="text-right px-3 py-3 font-normal">Length</th>
                <th className="text-right px-3 py-3 font-normal">Viewers</th>
                <th className="text-right px-3 py-3 font-normal">Engaged+</th>
                <th className="px-5 py-3" />
              </tr>
            </thead>
            <tbody>
              {jobs === null && !error && (
                <tr><td colSpan={8} className="px-5 py-8 text-center text-cv-sub text-xs font-mono">
                  <Loader2 size={14} className="animate-spin inline mr-2" />Loading...
                </td></tr>
              )}
              {jobs?.length === 0 && (
                <tr><td colSpan={8} className="px-5 py-10 text-center text-cv-sub text-sm">
                  No videos yet. <Link href="/dashboard" className="text-cv-accent hover:text-cv-accentL">Upload one</Link>.
                </td></tr>
              )}
              {jobs?.map(j => (
                <tr key={j.job_id}
                  onClick={() => setSelected(j)}
                  className={clsx('border-b border-cv-border/50 text-cv-text cursor-pointer hover:bg-cv-surface/60 transition-colors',
                    selected?.job_id === j.job_id && 'bg-cv-surface/60')}>
                  <td className="px-5 py-3 font-mono">{j.job_id}</td>
                  <td className="px-3 py-3">
                    <span className="flex items-center gap-2"><Film size={13} className="text-cv-accent flex-shrink-0" />
                      <span className="truncate max-w-[220px]">{j.filename}</span></span>
                  </td>
                  <td className="px-3 py-3 text-cv-sub text-xs font-mono">{new Date(j.created_at * 1000).toLocaleString()}</td>
                  <td className="px-3 py-3">
                    <span className={clsx('text-[11px] font-mono px-2 py-0.5 rounded', STATUS_BADGE[j.status])}>
                      {j.status === 'processing' ? `processing ${Math.round(j.progress)}%` : j.status}
                    </span>
                  </td>
                  <td className="px-3 py-3 text-right font-mono">{j.duration_sec != null ? `${j.duration_sec.toFixed(0)}s` : '-'}</td>
                  <td className="px-3 py-3 text-right font-mono">{j.status === 'done' ? j.viewers : '-'}</td>
                  <td className="px-3 py-3 text-right font-mono">{j.status === 'done' ? j.engaged + j.strong : '-'}</td>
                  <td className="px-5 py-3 text-right whitespace-nowrap">
                    <button onClick={e => { e.stopPropagation(); setSelected(j); }}
                      className="text-cv-accent hover:text-cv-accentL text-xs font-mono mr-4">View</button>
                    <button onClick={e => { e.stopPropagation(); handleDelete(j); }}
                      disabled={busy === j.job_id || j.status === 'processing' || j.status === 'queued'}
                      className="text-cv-sub hover:text-cv-red disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                      title="Delete">
                      {busy === j.job_id ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <AnimatePresence>
        {selected && <JobDrawer key={selected.job_id} job={selected} onClose={() => setSelected(null)} />}
      </AnimatePresence>
    </div>
  );
}
