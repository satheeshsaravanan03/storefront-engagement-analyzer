'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Eye, Upload, Settings2, Play, AlertTriangle, CheckCircle2,
  Loader2, Sliders, X, Wifi, WifiOff, Download,
  Activity, Users, Clock, Camera, Zap,
  ChevronRight, Film,
} from 'lucide-react';
import { uploadVideo, streamJobUpdates, checkBackendHealth, type AnalysisResult, type Zone } from '@/lib/api';
import { ZoneSelector } from '@/components/ZoneSelector';
import { EngagementResults } from '@/components/EngagementResults';
import clsx from 'clsx';

/* ── Inline video player with error handling ─────────────────
   The annotated MP4 is served from FastAPI at localhost:8000.
   We handle load errors gracefully with a fallback UI.
   ─────────────────────────────────────────────────────────── */
function VideoPlayerInline({ src }: { src: string }) {
  const [error, setError] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);

  // Reset state when src changes
  useEffect(() => { setError(false); setLoaded(false); }, [src]);

  return (
    <div className="relative bg-black" style={{ aspectRatio: '16/9' }}>
      {!loaded && !error && (
        <div className="absolute inset-0 flex items-center justify-center bg-cv-surface">
          <div className="text-center">
            <Loader2 size={28} className="text-cv-accent animate-spin mx-auto mb-2" />
            <p className="text-cv-sub text-xs font-mono">Loading annotated video...</p>
          </div>
        </div>
      )}

      {error && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-cv-surface gap-3 p-6">
          <AlertTriangle size={28} className="text-cv-amber" />
          <p className="text-cv-text font-semibold text-sm">Video preview unavailable</p>
          <p className="text-cv-sub text-xs text-center font-mono max-w-xs">
            The video file exists on the backend. Use the Open/Download button below to view it directly.
          </p>
          <a href={src} target="_blank" rel="noopener noreferrer"
            className="flex items-center gap-2 bg-cv-accent text-white text-xs font-semibold px-4 py-2 rounded-xl">
            <Play size={12} fill="currentColor" /> Open in new tab
          </a>
        </div>
      )}

      <video
        ref={videoRef}
        src={src}
        controls
        autoPlay
        loop
        muted
        playsInline
        className="w-full h-full object-contain"
        style={{ display: error ? 'none' : 'block' }}
        onLoadedData={() => setLoaded(true)}
        onError={() => setError(true)}
      />
    </div>
  );
}


/* ── Settings slider panel ────────────────────────────────── */
type Settings = { confidence: number; engage_sec: number; strong_sec: number; grace_sec: number };

function SettingsPanel({ config, onChange, onClose }: {
  config: Settings;
  onChange: (k: keyof Settings, v: number) => void;
  onClose: () => void;
}) {
  const sliders: { key: keyof Settings; label: string; min: number; max: number; step: number; hint?: string }[] = [
    { key: 'engage_sec',  label: 'Potential engagement from (sec)', min: 1,   max: 30, step: 1,   hint: 'Dwell at or above this is flagged' },
    { key: 'strong_sec',  label: 'Stronger signal from (sec)',      min: 2,   max: 60, step: 1,   hint: 'Dwell at or above this is a stronger signal' },
    { key: 'grace_sec',   label: 'Gap tolerance (sec)',             min: 0,   max: 5,  step: 0.5, hint: 'Short gaps in tracking are bridged, not split into two visits' },
    { key: 'confidence',  label: 'Detection confidence',            min: 0.2, max: 0.9, step: 0.05 },
  ];
  return (
    <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}
      className="glow-border bg-cv-card rounded-2xl p-6 space-y-5"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Sliders size={15} className="text-cv-accent" />
          <span className="font-semibold text-cv-text text-sm">Analysis Settings</span>
        </div>
        <button onClick={onClose} className="text-cv-sub hover:text-cv-text transition-colors"><X size={15} /></button>
      </div>
      {sliders.map(s => (
        <div key={s.key}>
          <div className="flex justify-between mb-1.5">
            <label className="text-sm text-cv-sub">{s.label}</label>
            <span className="font-mono text-cv-accent text-sm font-bold">{config[s.key]}</span>
          </div>
          <input type="range" min={s.min} max={s.max} step={s.step} value={config[s.key]}
            onChange={e => onChange(s.key, parseFloat(e.target.value))}
            className="w-full h-1.5 bg-cv-border rounded-full appearance-none cursor-pointer accent-cv-accent" />
          {s.hint && <p className="text-cv-sub text-[11px] mt-1">{s.hint}</p>}
        </div>
      ))}
    </motion.div>
  );
}

/* ── Drag-and-drop upload zone ────────────────────────────── */
function UploadZone({ onFile, disabled }: { onFile: (f: File) => void; disabled?: boolean }) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f && f.type.startsWith('video/')) onFile(f);
  }, [onFile]);

  return (
    <div
      onClick={() => !disabled && inputRef.current?.click()}
      onDragOver={e => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={clsx(
        'drop-zone border-2 border-dashed rounded-2xl p-14 cursor-pointer text-center transition-all duration-200',
        dragging ? 'dragging' : 'border-cv-border hover:border-cv-accent/40',
        disabled && 'opacity-50 cursor-not-allowed'
      )}
    >
      <input ref={inputRef} type="file" accept="video/*" className="hidden"
        onChange={e => { const f = e.target.files?.[0]; if (f) onFile(f); }} />
      <motion.div animate={{ y: dragging ? -10 : 0 }} className="flex flex-col items-center gap-5">
        <div className="w-20 h-20 rounded-2xl bg-cv-accent/10 border border-cv-accent/30 flex items-center justify-center">
          <Upload size={34} className="text-cv-accent" />
        </div>
        <div>
          <p className="text-cv-text font-semibold text-lg mb-1">Drop your video here</p>
          <p className="text-cv-sub text-sm">MP4 · AVI · MOV · MKV — up to 500 MB</p>
          <p className="text-cv-sub text-xs mt-2 font-mono">Prerecorded footage from a single storefront camera</p>
        </div>
        <div className="flex items-center gap-6 text-xs text-cv-sub font-mono flex-wrap justify-center">
          <span className="flex items-center gap-1.5"><Camera size={11} className="text-cv-accent" />YOLOv8 detection</span>
          <span className="flex items-center gap-1.5"><Activity size={11} className="text-cv-cyan" />ByteTrack IDs</span>
          <span className="flex items-center gap-1.5"><Users size={11} className="text-cv-green" />Storefront zone</span>
          <span className="flex items-center gap-1.5"><Clock size={11} className="text-cv-amber" />Dwell time</span>
        </div>
      </motion.div>
    </div>
  );
}

/* ── Live preview frame ───────────────────────────────────── */
function LivePreview({ result }: { result: AnalysisResult }) {
  const fd = result.frame_data;
  const pct = Math.round(result.progress ?? 0);

  return (
    <div className="space-y-4">
      {/* Progress bar */}
      <div className="glow-border bg-cv-card rounded-2xl p-4">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <Loader2 size={14} className="text-cv-accent animate-spin" />
            <span className="text-sm font-semibold text-cv-text">Processing...</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-cv-sub text-xs font-mono">
              {result.processed_frames ?? 0} / {result.total_frames ?? '?'} frames
            </span>
            <span className="font-mono text-cv-accent font-bold">{pct}%</span>
          </div>
        </div>
        <div className="h-2 bg-cv-border rounded-full overflow-hidden">
          <motion.div
            className="h-full rounded-full"
            style={{ background: 'linear-gradient(90deg, #6C63FF, #06B6D4)' }}
            animate={{ width: `${pct}%` }}
            transition={{ duration: 0.4, ease: 'easeOut' }}
          />
        </div>
        <div className="flex justify-between mt-1.5 text-[11px] text-cv-sub font-mono">
          <span>{(result.fps ?? 0).toFixed(1)} FPS processing</span>
          <span>{pct < 100 ? 'Running YOLOv8n + ByteTrack...' : 'Finalising...'}</span>
        </div>
      </div>

      {/* Live annotated frame streamed from the backend */}
      {result.preview_frame ? (
        <div className="relative rounded-2xl overflow-hidden border border-cv-border bg-black">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={`data:image/jpeg;base64,${result.preview_frame}`}
            alt="Live pipeline preview"
            className="w-full object-cover"
            style={{ aspectRatio: '16/9' }}
          />
          <div className="absolute top-3 left-3 flex items-center gap-1.5 bg-black/75 backdrop-blur-sm px-3 py-1.5 rounded-lg">
            <div className="w-2 h-2 bg-cv-green rounded-full animate-pulse" />
            <span className="text-cv-green font-mono text-[11px] font-bold">LIVE PREVIEW</span>
          </div>
          <div className="absolute top-3 right-3 bg-black/75 backdrop-blur-sm px-3 py-1.5 rounded-lg">
            <span className="text-cv-sub font-mono text-[11px]">
              {(result.fps ?? 0).toFixed(1)} FPS · Frame {result.processed_frames}
            </span>
          </div>
        </div>
      ) : (
        <div className="rounded-2xl border border-cv-border bg-cv-surface flex items-center justify-center" style={{ aspectRatio: '16/9' }}>
          <div className="text-center">
            <Loader2 size={32} className="text-cv-accent animate-spin mx-auto mb-3" />
            <p className="text-cv-sub text-sm">Loading first frame...</p>
          </div>
        </div>
      )}

      {/* Live counters under the preview */}
      {fd && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: 'Video time',     value: `${fd.time_sec.toFixed(1)}s`, color: 'text-cv-cyan'  },
            { label: 'In zone now',    value: fd.in_zone_now,               color: 'text-cv-accent' },
            { label: 'Tracked visits', value: fd.visits,                    color: 'text-cv-text'  },
            { label: 'Potential / strong', value: `${fd.potential} / ${fd.strong}`, color: 'text-cv-amber' },
          ].map(({ label, value, color }) => (
            <div key={label} className="glow-border bg-cv-card rounded-2xl p-4">
              <p className={clsx('font-display text-2xl', color)}>{value}</p>
              <p className="text-cv-sub text-xs font-mono mt-1">{label}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Full results panel (shown after processing completes) ─── */
function ResultsPanel({ result, jobId, engageSec, strongSec, onThreshold }: {
  result: AnalysisResult;
  jobId: string;
  engageSec: number;
  strongSec: number;
  onThreshold: (k: 'engage_sec' | 'strong_sec', v: number) => void;
}) {
  const stats = result.stats;
  const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

  return (
    <div className="space-y-5">
      {/* Success banner */}
      <motion.div initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }}
        className="glow-border bg-cv-green/5 border-cv-green/30 rounded-2xl p-5 flex items-center gap-4"
      >
        <CheckCircle2 size={24} className="text-cv-green flex-shrink-0" />
        <div className="flex-1">
          <p className="font-semibold text-cv-text">Analysis complete!</p>
          <p className="text-cv-sub text-sm">
            {stats?.total_frames ?? result.total_frames} frames · {stats?.duration_sec?.toFixed(1)}s video · {stats?.resolution}
          </p>
        </div>
        <a href={`${BACKEND}/api/download/${jobId}/zip`}
          className="flex items-center gap-2 bg-cv-accent hover:bg-cv-accentL text-white text-sm font-semibold px-4 py-2.5 rounded-xl transition-colors flex-shrink-0">
          <Download size={15} /> Download ZIP
        </a>
      </motion.div>

      {/* Adjustable thresholds — results below update instantly */}
      <div className="glow-border bg-cv-card rounded-2xl p-4 flex items-center gap-4 flex-wrap">
        <span className="text-cv-sub text-xs font-mono">THRESHOLDS</span>
        <label className="flex items-center gap-2 text-sm text-cv-sub">
          Potential from
          <input type="number" min={1} max={strongSec} value={engageSec}
            onChange={e => onThreshold('engage_sec', Math.max(1, parseFloat(e.target.value) || 1))}
            className="w-16 bg-cv-surface border border-cv-border rounded-lg px-2 py-1 text-cv-text font-mono text-sm" /> s
        </label>
        <label className="flex items-center gap-2 text-sm text-cv-sub">
          Stronger from
          <input type="number" min={engageSec} value={strongSec}
            onChange={e => onThreshold('strong_sec', Math.max(engageSec, parseFloat(e.target.value) || engageSec))}
            className="w-16 bg-cv-surface border border-cv-border rounded-lg px-2 py-1 text-cv-text font-mono text-sm" /> s
        </label>
        <span className="text-cv-sub text-[11px] ml-auto">Table and counts update live. The annotated video keeps the thresholds used when it was processed.</span>
      </div>

      {/* Annotated video player — inline on the website */}
      {result.annotated_video_url && (
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}
          className="glow-border bg-cv-card rounded-2xl overflow-hidden"
        >
          <div className="px-5 py-3 border-b border-cv-border flex items-center gap-2">
            <Film size={15} className="text-cv-accent" />
            <span className="font-semibold text-cv-text text-sm">Annotated Output Video</span>
            <span className="text-cv-sub text-xs font-mono ml-auto">
              Boxes · Track IDs · Live dwell · Storefront zone
            </span>
          </div>

          <VideoPlayerInline src={result.annotated_video_url} />

          <div className="px-5 py-3 flex items-center justify-between border-t border-cv-border">
            <span className="text-cv-sub text-xs font-mono">
              {stats?.source_fps?.toFixed(1)} FPS · {stats?.resolution} · {stats?.total_frames} frames
            </span>
            <a href={result.annotated_video_url}
              target="_blank" rel="noopener noreferrer"
              className="flex items-center gap-1.5 text-cv-accent hover:text-cv-accentL text-xs font-mono transition-colors">
              <Download size={12} /> Open / Download MP4
            </a>
          </div>
        </motion.div>
      )}

      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
        <EngagementResults
          visits={result.visits ?? []}
          engageSec={engageSec}
          strongSec={strongSec}
          durationSec={stats?.duration_sec ?? 0}
          csvUrl={result.visits_url}
        />
      </motion.div>
    </div>
  );
}

/* ── Main dashboard page ──────────────────────────────────── */
export default function DashboardPage() {
  const [file, setFile]               = useState<File | null>(null);
  const [zone, setZone]               = useState<Zone | null>(null);
  const [jobId, setJobId]             = useState<string | null>(null);
  const [result, setResult]           = useState<AnalysisResult | null>(null);
  const [state, setState]             = useState<'idle'|'uploading'|'processing'|'done'|'error'>('idle');
  const [error, setError]             = useState<string | null>(null);
  const [showConfig, setShowConfig]   = useState(false);
  const [backendOnline, setBackend]   = useState<boolean | null>(null);
  const [config, setConfig]           = useState<Settings>({
    confidence: 0.40, engage_sec: 5, strong_sec: 10, grace_sec: 1.5,
  });
  const stopStream = useRef<(()=>void)|null>(null);

  useEffect(() => { checkBackendHealth().then(setBackend); }, []);

  // Keep strong >= engage whichever one the user moves
  const setSetting = useCallback((k: keyof Settings, v: number) => {
    setConfig(p => {
      const next = { ...p, [k]: v };
      if (k === 'engage_sec' && next.strong_sec < v) next.strong_sec = v;
      if (k === 'strong_sec' && next.engage_sec > v) next.engage_sec = v;
      return next;
    });
  }, []);

  const handleFile = useCallback((f: File) => {
    setFile(f); setZone(null); setResult(null); setState('idle'); setError(null);
  }, []);

  const handleStart = async () => {
    if (!file || !zone) return;
    setState('uploading'); setError(null);
    try {
      const { job_id } = await uploadVideo(file, { ...config, zone });
      setJobId(job_id); setState('processing');
      stopStream.current = streamJobUpdates(
        job_id,
        upd => setResult(upd),
        done => { setResult(done); setState('done'); },
        err  => { setError(err); setState('error'); }
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed');
      setState('error');
    }
  };

  const handleReset = () => {
    stopStream.current?.();
    setFile(null); setZone(null); setJobId(null); setResult(null);
    setState('idle'); setError(null);
  };

  const canStart = !!file && !!zone && !!backendOnline && state !== 'uploading';

  return (
    <div className="noise mesh-bg min-h-screen">
      {/* Nav */}
      <nav className="border-b border-cv-border bg-cv-surface/80 backdrop-blur-xl px-6 py-4 flex items-center justify-between sticky top-0 z-40">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 bg-gradient-to-br from-cv-accent to-cv-cyan rounded-lg flex items-center justify-center">
              <Eye size={13} className="text-white" />
            </div>
            <span className="font-display text-lg text-cv-text">Storefront Engagement</span>
            <ChevronRight size={14} className="text-cv-border" />
            <span className="text-cv-sub text-sm">Analysis</span>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Backend indicator */}
          <div className={clsx(
            'flex items-center gap-1.5 text-xs font-mono px-3 py-1.5 rounded-full border',
            backendOnline === null ? 'border-cv-border text-cv-sub' :
            backendOnline  ? 'border-cv-green/30 text-cv-green bg-cv-green/5' :
                             'border-cv-red/30 text-cv-red bg-cv-red/5'
          )}>
            {backendOnline === null ? <Loader2 size={11} className="animate-spin" /> :
             backendOnline  ? <Wifi size={11} />   : <WifiOff size={11} />}
            {backendOnline === null ? 'Checking...' :
             backendOnline  ? 'Backend Online' : 'Backend Offline'}
          </div>

          {state === 'idle' && file && (
            <button onClick={() => setShowConfig(!showConfig)}
              className={clsx('glow-border bg-cv-card px-3 py-1.5 rounded-xl text-sm flex items-center gap-2 transition-colors',
                showConfig ? 'text-cv-accent' : 'text-cv-sub hover:text-cv-text')}>
              <Settings2 size={14} /> Settings
            </button>
          )}

          {state === 'done' && (
            <button onClick={handleReset}
              className="glow-border bg-cv-card text-cv-sub hover:text-cv-text px-3 py-1.5 rounded-xl text-sm flex items-center gap-2 transition-colors">
              <Upload size={14} /> New Video
            </button>
          )}
        </div>
      </nav>

      <div className="max-w-6xl mx-auto px-6 py-8">
        {/* Header */}
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="mb-8">
          <h1 className="font-display text-4xl text-cv-text mb-2">
            {state === 'done' ? 'Analysis Complete' :
             state === 'processing' ? 'Processing...' :
             'Storefront Engagement Analysis'}
          </h1>
          <p className="text-cv-sub">
            {state === 'idle'       && (file
              ? 'Mark the area in front of the store on the video, then start the analysis.'
              : 'Upload a prerecorded storefront video to measure how long people stay near the shop.')}
            {state === 'uploading'  && 'Uploading your video to the backend...'}
            {state === 'processing' && 'YOLOv8n + ByteTrack running frame by frame. Preview updates live.'}
            {state === 'done'       && 'Visits, engagement counts, the annotated video and CSV are ready below.'}
            {state === 'error'      && 'Something went wrong. See error details below.'}
          </p>
        </motion.div>

        <div className="grid md:grid-cols-3 gap-6">
          {/* Main column — 2/3 width */}
          <div className="md:col-span-2 space-y-4">
            {/* Upload / preview + zone */}
            <AnimatePresence>
              {(state === 'idle' || state === 'uploading') && (
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-3">
                  {!file && <UploadZone onFile={handleFile} disabled={state === 'uploading'} />}

                  {file && (
                    <>
                      <div className="glow-border bg-cv-card rounded-xl p-4 flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          <div className="w-9 h-9 bg-cv-accent/10 rounded-lg flex items-center justify-center">
                            <Film size={16} className="text-cv-accent" />
                          </div>
                          <div>
                            <p className="text-cv-text text-sm font-medium">{file.name}</p>
                            <p className="text-cv-sub text-xs font-mono">{(file.size/1e6).toFixed(1)} MB · {file.type}</p>
                          </div>
                        </div>
                        <button onClick={handleReset} className="text-cv-sub hover:text-cv-red transition-colors"><X size={16} /></button>
                      </div>

                      <ZoneSelector file={file} zone={zone} onChange={setZone} />
                    </>
                  )}

                  <AnimatePresence>
                    {showConfig && file && (
                      <motion.div>
                        <SettingsPanel config={config} onChange={setSetting} onClose={() => setShowConfig(false)} />
                      </motion.div>
                    )}
                  </AnimatePresence>

                  {file && (
                    <motion.button initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                      onClick={handleStart}
                      disabled={!canStart}
                      whileHover={{ scale: canStart ? 1.02 : 1 }} whileTap={{ scale: canStart ? 0.98 : 1 }}
                      className={clsx(
                        'w-full py-4 rounded-2xl font-semibold text-base flex items-center justify-center gap-3 transition-all',
                        canStart ? 'bg-cv-accent hover:bg-cv-accentL text-white' : 'bg-cv-muted text-cv-sub cursor-not-allowed',
                        state === 'uploading' && 'opacity-70 cursor-wait'
                      )}
                    >
                      {state === 'uploading'
                        ? <><Loader2 size={18} className="animate-spin" /> Uploading...</>
                        : <><Play size={18} fill="currentColor" /> {zone ? 'Start Analysis' : 'Draw the storefront zone to start'}</>
                      }
                    </motion.button>
                  )}

                  {backendOnline === false && (
                    <p className="text-cv-red text-xs text-center mt-2 font-mono">
                      ⚠ Backend offline. Run: uvicorn main:app --reload --port 8000
                    </p>
                  )}
                </motion.div>
              )}
            </AnimatePresence>

            {/* LIVE PREVIEW during processing */}
            <AnimatePresence>
              {state === 'processing' && result && (
                <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
                  <LivePreview result={result} />
                </motion.div>
              )}
            </AnimatePresence>

            {/* FULL RESULTS after done */}
            <AnimatePresence>
              {state === 'done' && result && jobId && (
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                  <ResultsPanel
                    result={result} jobId={jobId}
                    engageSec={config.engage_sec} strongSec={config.strong_sec}
                    onThreshold={setSetting}
                  />
                </motion.div>
              )}
            </AnimatePresence>

            {/* Error */}
            <AnimatePresence>
              {state === 'error' && (
                <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
                  className="glow-border bg-cv-red/5 border-cv-red/30 rounded-2xl p-5 flex items-start gap-4"
                >
                  <AlertTriangle size={20} className="text-cv-red flex-shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <p className="font-semibold text-cv-text mb-1">Processing failed</p>
                    <p className="text-cv-sub text-sm font-mono">{error}</p>
                  </div>
                  <button onClick={handleReset} className="text-cv-sub hover:text-cv-text"><X size={16} /></button>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* Sidebar — 1/3 width */}
          <div className="space-y-4">
            {/* Pipeline steps */}
            <div className="glow-border bg-cv-card rounded-2xl p-5">
              <p className="text-xs font-mono text-cv-sub mb-4 tracking-wider">PIPELINE</p>
              {[
                { n:'01', label:'YOLOv8n Detection',   color:'bg-cv-accent', done: ['processing','done'].includes(state) },
                { n:'02', label:'ByteTrack IDs',        color:'bg-cv-cyan',   done: ['processing','done'].includes(state) },
                { n:'03', label:'Storefront Zone Test', color:'bg-cv-green',  done: ['processing','done'].includes(state) },
                { n:'04', label:'Dwell Time',           color:'bg-cv-amber',  done: state === 'done' },
                { n:'05', label:'Engagement Classes',   color:'bg-purple-500', done: state === 'done' },
              ].map(({ n, label, color, done }) => (
                <div key={n} className="flex items-center gap-3 mb-3">
                  <div className={clsx(
                    'w-6 h-6 rounded-md flex items-center justify-center flex-shrink-0 transition-all duration-500',
                    done ? color : 'bg-cv-border'
                  )}>
                    {done
                      ? <CheckCircle2 size={13} className="text-white" />
                      : <span className="text-[9px] font-mono text-cv-sub font-bold">{n}</span>
                    }
                  </div>
                  <span className={clsx('text-sm transition-colors duration-300', done ? 'text-cv-text' : 'text-cv-sub')}>{label}</span>
                </div>
              ))}
            </div>

            {/* What you'll get */}
            <div className="glow-border bg-cv-card rounded-2xl p-5">
              <p className="text-xs font-mono text-cv-sub mb-4 tracking-wider">YOU WILL GET</p>
              {[
                { e:'🎬', l:'Annotated video (MP4)'   },
                { e:'👣', l:'Tracked visits + dwell'  },
                { e:'🎯', l:'Engagement classes'      },
                { e:'📋', l:'visits.csv'              },
                { e:'📦', l:'All files as ZIP'        },
              ].map(({ e, l }) => (
                <div key={l} className="flex items-center gap-2 mb-2 text-sm text-cv-sub">
                  <span className="text-base">{e}</span>
                  <span className="font-mono text-xs">{l}</span>
                </div>
              ))}
            </div>

            {/* Tips */}
            <div className="glow-border bg-cv-card rounded-2xl p-5">
              <p className="text-xs font-mono text-cv-sub mb-4 tracking-wider">TIPS</p>
              {[
                'Draw the zone on the floor area in front of the shop',
                'Keep videos under 100 MB for fast processing',
                'Thresholds can be changed after processing',
                'Download ZIP before refreshing the page',
              ].map(t => (
                <div key={t} className="flex items-start gap-2 mb-3">
                  <Zap size={12} className="text-cv-accent mt-0.5 flex-shrink-0" />
                  <span className="text-cv-sub text-xs leading-relaxed">{t}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
