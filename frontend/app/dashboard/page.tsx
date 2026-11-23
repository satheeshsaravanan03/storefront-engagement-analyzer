'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Upload, Play, AlertTriangle, CheckCircle2,
  Loader2, Sliders, X, Download, Zap, Film,
  ChevronDown, Plus, Eye, Store,
} from 'lucide-react';
import { uploadVideo, streamJobUpdates, checkBackendHealth, type AnalysisMode, type AnalysisResult, type Place } from '@/lib/api';
import { SummaryCards, UploadedVideo, ViewersTable } from '@/components/EngagementResults';
import { MatchedLeads } from '@/components/MatchedLeads';
import { PlaceMarker, draftsReady, newDraft, toPlaces, type PlaceDraft } from '@/components/PlaceMarker';
import { AnnotatedVideo } from '@/components/AnnotatedVideo';
import { PlaceMarks } from '@/components/PlaceMarks';
import { fitRect } from '@/lib/fit';
import { PlaceResults } from '@/components/PlaceResults';
import { AppShell } from '@/components/AppShell';
import clsx from 'clsx';

/* ── Local preview of the chosen file, before upload ───────── */
function VideoPreview({ file, hint }: { file: File; hint: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const u = URL.createObjectURL(file);
    setUrl(u); setFailed(false);
    return () => URL.revokeObjectURL(u);
  }, [file]);
  if (!url) return null;
  return (
    <div className="glow-border bg-cv-card rounded-2xl overflow-hidden">
      <div className="relative bg-black">
        <video src={url} controls muted playsInline className="w-full bg-black" style={{ maxHeight: 420 }}
          onError={() => setFailed(true)} />
        {failed && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-cv-surface gap-2 p-6 text-center">
            <AlertTriangle size={26} className="text-cv-amber" />
            <p className="text-cv-text font-semibold text-sm">This browser cannot play this video</p>
            <p className="text-cv-sub text-xs max-w-sm">
              The file uses a codec the browser does not support (for example H.265). You can still analyse it; the preview just cannot be shown.
            </p>
          </div>
        )}
      </div>
      <p className="px-4 py-2 text-cv-sub text-xs font-mono border-t border-cv-border">{hint}</p>
    </div>
  );
}

/* ── Settings ─────────────────────────────────────────────── */
// Detection confidence (0.40) and nearness (0.30) are fixed constants in lib/api.ts, not user settings
type Settings = {
  glance_sec: number; engage_sec: number; strong_sec: number; min_look_sec: number;
};

const PRESETS: { name: string; values: Settings }[] = [
  { name: 'Lenient',  values: { glance_sec: 1.5, engage_sec: 3, strong_sec: 6,  min_look_sec: 0.5 } },
  { name: 'Balanced', values: { glance_sec: 2,   engage_sec: 5, strong_sec: 10, min_look_sec: 1 } },
  { name: 'Strict',   values: { glance_sec: 3,   engage_sec: 7, strong_sec: 15, min_look_sec: 1.5 } },
];
const DEFAULT_SETTINGS = PRESETS.find(p => p.name === 'Balanced')!.values;
const sameSettings = (a: Settings, b: Settings) =>
  (Object.keys(a) as (keyof Settings)[]).every(k => a[k] === b[k]);

// Mall places: how long inside counts as entered, and how long standing in front counts as stopped
type PlaceSettings = { stay_sec: number; stop_sec: number };
const DEFAULT_PLACE_SETTINGS: PlaceSettings = { stay_sec: 2.5, stop_sec: 3 };

const LEVEL_COLORS = ['#E4E6F0', '#C9CCF7', '#8F8AF0', '#4F46E5', '#2E2A86'];

/* Bar showing how the thresholds split attention time into levels */
function LevelBar({ c }: { c: Settings }) {
  const b = [0, c.min_look_sec, c.glance_sec, c.engage_sec, c.strong_sec];
  for (let i = 1; i < b.length; i++) b[i] = Math.max(b[i], b[i - 1]);   // keep in order if one is dragged past another
  const total = b[4] * 1.35 || 1;
  const widths = [b[1] - b[0], b[2] - b[1], b[3] - b[2], b[4] - b[3], total - b[4]];
  const legend = [
    ['Not counted', `< ${c.min_look_sec} s`],
    ['Glance',      `${c.min_look_sec}–${c.glance_sec} s`],
    ['Looked',      `${c.glance_sec}–${c.engage_sec} s`],
    ['Engaged',     `${c.engage_sec}–${c.strong_sec} s`],
    ['Strong',      `≥ ${c.strong_sec} s`],
  ];
  return (
    <div className="rounded-2xl bg-cv-black p-4">
      <div className="flex h-3 rounded-full overflow-hidden gap-0.5">
        {widths.map((w, i) => (
          <div key={i} style={{ width: `${(w / total) * 100}%`, background: LEVEL_COLORS[i] }} />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-5 gap-y-2 mt-4 text-sm">
        {legend.map(([name, range], i) => (
          <div key={name} className="flex items-center gap-2 whitespace-nowrap">
            <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ background: LEVEL_COLORS[i] }} />
            <span className="text-cv-text">{name}</span>
            <span className="font-mono text-xs text-cv-sub whitespace-nowrap">{range}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function SettingSlider({ label, value, min, max, step, unit, hint, onChange }: {
  label: string; value: number; min: number; max: number; step: number;
  unit?: string; hint?: string; onChange: (v: number) => void;
}) {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <div>
      <div className="flex items-center justify-between mb-2.5">
        <label className="text-sm font-medium text-cv-text">{label}</label>
        <span className="font-mono text-xs font-semibold text-cv-accent bg-cv-accent/10 px-2 py-1 rounded-md">
          {unit ? `${value} ${unit}` : value.toFixed(2)}
        </span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={e => onChange(parseFloat(e.target.value))}
        className="cv-range w-full"
        style={{ background: `linear-gradient(to right, #4F46E5 ${pct}%, #E2E4EE ${pct}%)` }} />
      {hint && <p className="text-cv-sub text-xs mt-2">{hint}</p>}
    </div>
  );
}

function SettingsPanel({ config, onChange, onPreset }: {
  config: Settings;
  onChange: (k: keyof Settings, v: number) => void;
  onPreset: (v: Settings) => void;
}) {
  return (
    <div className="glow-border bg-cv-card p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <Sliders size={16} className="text-cv-accent" />
          <span className="font-semibold text-cv-text text-lg">Analysis settings</span>
        </div>
        <button onClick={() => onPreset(DEFAULT_SETTINGS)} className="text-cv-accent hover:text-cv-accentL text-sm font-semibold">Reset</button>
      </div>

      <div>
        <p className="text-[11px] font-semibold tracking-wider text-cv-sub mb-2.5">PRESET</p>
        <div className="flex gap-2 flex-wrap">
          {PRESETS.map(p => (
            <button key={p.name} onClick={() => onPreset(p.values)}
              className={clsx('px-4 py-2 rounded-full text-sm font-medium border transition-colors',
                sameSettings(config, p.values)
                  ? 'bg-cv-accent text-white border-cv-accent'
                  : 'bg-cv-card text-cv-text border-cv-border hover:border-cv-accent/40')}>
              {p.name}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-5">
        <div>
          <p className="font-semibold text-cv-text">Attention levels</p>
          <p className="text-cv-sub text-sm mt-1">Seconds of facing the display needed to reach each level.</p>
        </div>
        <LevelBar c={config} />
        <SettingSlider label="Minimum look to count" unit="s" min={0.5} max={5} step={0.5} value={config.min_look_sec}
          hint="Shorter looks are not counted as viewers" onChange={v => onChange('min_look_sec', v)} />
        <SettingSlider label="Stopped & looked from" unit="s" min={1} max={10} step={0.5} value={config.glance_sec}
          hint="Below this, a look is only a glance" onChange={v => onChange('glance_sec', v)} />
        <SettingSlider label="Engaged from" unit="s" min={1} max={30} step={1} value={config.engage_sec}
          hint="Attention at or above this is potential engagement" onChange={v => onChange('engage_sec', v)} />
        <SettingSlider label="Strongly engaged from" unit="s" min={2} max={60} step={1} value={config.strong_sec}
          hint="Attention at or above this is a stronger signal" onChange={v => onChange('strong_sec', v)} />
      </div>

    </div>
  );
}

function PlaceSettingsPanel({ config, onChange }: {
  config: PlaceSettings;
  onChange: (k: keyof PlaceSettings, v: number) => void;
}) {
  return (
    <div className="glow-border bg-cv-card p-6 space-y-6">
      <div className="flex items-center gap-2.5">
        <Sliders size={16} className="text-cv-accent" />
        <span className="font-semibold text-cv-text text-lg">Mall settings</span>
      </div>
      <SettingSlider label="Inside to count as entered" unit="s" min={0.5} max={10} step={0.5} value={config.stay_sec}
        hint="Stepping in and straight back out sooner than this is a peek, not an entry. Going out of view inside also counts."
        onChange={v => onChange('stay_sec', v)} />
      <SettingSlider label="Standing in front to count as stopped" unit="s" min={1} max={30} step={0.5} value={config.stop_sec}
        hint="Time standing nearly still in the front area. Needs a front area marked for the shop."
        onChange={v => onChange('stop_sec', v)} />
      <p className="text-cv-sub text-xs leading-relaxed">
        People are detected and tracked automatically. Only their feet are checked against the marks you draw.
      </p>
    </div>
  );
}

/* Which kind of analysis: attention at one display, or movement in and out of several shops. */
function ModeSwitch({ mode, onChange }: { mode: AnalysisMode; onChange: (m: AnalysisMode) => void }) {
  const opts: { id: AnalysisMode; icon: typeof Eye; title: string; text: string }[] = [
    { id: 'stand',  icon: Eye,   title: 'Stand attention', text: 'Who looked at one display, and for how long' },
    { id: 'places', icon: Store, title: 'Mall places',     text: 'Who went into, left or stopped at each shop' },
  ];
  return (
    <div className="grid sm:grid-cols-2 gap-3">
      {opts.map(({ id, icon: Icon, title, text }) => (
        <button key={id} onClick={() => onChange(id)} aria-pressed={mode === id}
          className={clsx('text-left rounded-2xl border p-4 transition-colors flex items-start gap-3',
            mode === id ? 'bg-cv-accent/[0.06] border-cv-accent' : 'bg-cv-card border-cv-border hover:border-cv-accent/40')}>
          <Icon size={18} className={clsx('mt-0.5 flex-shrink-0', mode === id ? 'text-cv-accent' : 'text-cv-sub')} />
          <span>
            <span className="block font-semibold text-cv-text">{title}</span>
            <span className="block text-cv-sub text-sm mt-0.5">{text}</span>
          </span>
        </button>
      ))}
    </div>
  );
}

/* ── Start button, shown right under the video preview ───── */
function StartButton({ onStart, canStart, starting, backendOnline, note }: {
  onStart: () => void;
  canStart: boolean;
  starting: boolean;
  backendOnline: boolean | null;
  note?: string;   // shown instead of "Ready" while something is still missing
}) {
  return (
    <div>
      <button onClick={onStart} disabled={!canStart}
        className={clsx('w-full py-4 rounded-2xl font-semibold text-base flex items-center justify-center gap-2.5 transition-colors',
          canStart ? 'bg-cv-accent hover:bg-cv-accentL text-white' : 'bg-cv-muted text-cv-sub cursor-not-allowed',
          starting && 'opacity-70 cursor-wait')}>
        {starting
          ? <><Loader2 size={17} className="animate-spin" /> Uploading...</>
          : <><Play size={16} fill="currentColor" /> Analyse video</>}
      </button>
      <p className={clsx('text-center text-sm mt-2.5', backendOnline === false ? 'text-cv-red' : 'text-cv-sub')}>
        {backendOnline === false ? 'Backend offline. Run: uvicorn main:app --port 8000'
          : note ?? 'Ready. The analysis runs on the backend.'}
      </p>
    </div>
  );
}

/* ── Drag-and-drop upload zone ────────────────────────────── */
function UploadZone({ onFile, disabled, note }: { onFile: (f: File) => void; disabled?: boolean; note: string }) {
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
        'drop-zone border-2 border-dashed rounded-3xl px-8 py-14 cursor-pointer text-center transition-all duration-200',
        dragging ? 'dragging' : 'border-cv-accent/30 bg-cv-accent/[0.03] hover:border-cv-accent/50',
        disabled && 'opacity-50 cursor-not-allowed'
      )}
    >
      <input ref={inputRef} type="file" accept="video/*" className="hidden"
        onChange={e => { const f = e.target.files?.[0]; if (f) onFile(f); }} />
      <div className="flex flex-col items-center gap-5">
        <div className="w-16 h-16 rounded-2xl bg-cv-accent/10 flex items-center justify-center">
          <Upload size={28} className="text-cv-accent" />
        </div>
        <div>
          <p className="text-cv-text font-semibold text-2xl mb-1.5">Drop your video here</p>
          <p className="text-cv-sub">or choose a file from your computer</p>
        </div>
        <button type="button" disabled={disabled}
          onClick={e => { e.stopPropagation(); inputRef.current?.click(); }}
          className="bg-cv-accent hover:bg-cv-accentL text-white font-semibold px-6 py-3 rounded-xl transition-colors">
          Choose video
        </button>
        <div className="flex items-center gap-2 flex-wrap justify-center">
          {['MP4', 'AVI', 'MOV', 'MKV'].map(t => (
            <span key={t} className="font-mono text-xs text-cv-sub border border-cv-border rounded-full px-3 py-1 bg-cv-card">{t}</span>
          ))}
          <span className="text-cv-sub text-sm ml-1">Up to 500 MB</span>
        </div>
        <p className="text-cv-sub text-sm">{note}</p>
      </div>
    </div>
  );
}

/* ── Explainer cards under the drop zone ──────────────────── */
const STAND_STEPS = [
  ['01', 'Detect people',                 'YOLOv8 pose finds every person in each frame.'],
  ['02', 'Track each visitor',            'ByteTrack IDs keep one identity per person across frames.'],
  ['03', 'Check who faces the display',   'Head and body pose decide whether someone is looking.'],
  ['04', 'Measure attention time',        'Look duration is grouped into the levels you set.'],
];
const PLACES_STEPS = [
  ['01', 'Mark the shops',           'Draw a door line on the floor for each shop and click which side is inside.'],
  ['02', 'Track everyone',           'Every person gets an ID that follows them through the video.'],
  ['03', 'Watch the feet',           'Only the feet are checked against your marks, so a body in front of a shop does not count as inside.'],
  ['04', 'Count entries and visits', 'Who entered, left or stopped at each shop, and who went into more than one.'],
];

function HowItWorks({ steps }: { steps: string[][] }) {
  return (
    <div className="glow-border bg-cv-card p-6">
      <p className="font-semibold text-cv-text text-lg mb-4">How the analysis works</p>
      <div className="grid sm:grid-cols-3 gap-3">
        {steps.map(([n, title, text], i) => (
          <div key={n} className={clsx('rounded-2xl border border-cv-border p-4', i === 3 && 'sm:col-span-3')}>
            <p className="font-mono text-xs text-cv-accent mb-2">{n}</p>
            <p className="font-semibold text-cv-text mb-1">{title}</p>
            <p className="text-cv-sub text-sm leading-relaxed">{text}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

const STAND_TIPS = [
  'Mount the camera at the display, at head height, facing visitors',
  'People far away or turned away are not counted',
  'Keep videos under 100 MB for fast processing',
  'Set the thresholds before uploading; they apply to the whole analysis',
  'Every analysis is saved on the Jobs page',
];
const PLACES_TIPS = [
  'Use a fixed camera, high up, that sees the floor and every shop door; a moving camera breaks the marks',
  'Draw the door line on the floor where the shop meets the walkway, not on the shop window',
  'Click inside the shop to say which side is in; check the IN arrow points into the shop',
  'Mark a front area too, to count people who stop at a shop without going in',
  'Mall videos take longer to analyse than stand videos: people are small and the whole frame is searched',
  'Every analysis is saved on the Jobs page',
];

function TipsAccordion({ tips }: { tips: string[] }) {
  return (
    <details className="glow-border bg-cv-card group">
      <summary className="flex items-center justify-between px-6 py-5 cursor-pointer select-none list-none">
        <span className="font-semibold text-cv-text text-lg">Tips for reliable results</span>
        <ChevronDown size={18} className="text-cv-sub transition-transform group-open:rotate-180" />
      </summary>
      <div className="px-6 pb-5 space-y-3">
        {tips.map(t => (
          <div key={t} className="flex items-start gap-2.5">
            <Zap size={13} className="text-cv-accent mt-1 flex-shrink-0" />
            <span className="text-cv-sub text-sm leading-relaxed">{t}</span>
          </div>
        ))}
      </div>
    </details>
  );
}

/* ── Live preview frame ───────────────────────────────────── */
function LivePreview({ result, marks }: { result: AnalysisResult; marks?: Place[] }) {
  const fd = result.frame_data;
  const places = result.mode === 'places';
  const pct = Math.round(result.progress ?? 0);

  // Mall frames are shown whole and in their own shape, with the shops drawn over the picture by the page (as on the
  // finished video). The marks are placed on the picture itself, so they hold for a video of any shape.
  const boxRef = useRef<HTMLDivElement>(null);
  const [shape, setShape] = useState<{ w: number; h: number } | null>(null);   // size of the preview picture
  const [box, setBox] = useState<{ w: number; h: number } | null>(null);       // size of the box it is shown in
  const hasFrame = !!result.preview_frame;
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setBox({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, [hasFrame]);
  const natural = places && !!shape;
  const fit = marks && box && shape ? fitRect(box, shape) : null;

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
            initial={{ width: 0 }}
            animate={{ width: `${pct}%` }}
            transition={{ duration: 0.4, ease: 'easeOut' }}
          />
        </div>
        <div className="flex justify-between mt-1.5 text-[11px] text-cv-sub font-mono">
          <span>{(result.fps ?? 0).toFixed(1)} FPS processing</span>
          <span>
            {pct >= 100 ? 'Finalising...'
              : places ? `${result.phase ?? 'tracking people'}...`.replace(/^./, c => c.toUpperCase())
              : 'Running pose detection + ByteTrack...'}
          </span>
        </div>
      </div>

      {/* Live annotated frame streamed from the backend */}
      {result.preview_frame ? (
        <div ref={boxRef} className="relative rounded-2xl overflow-hidden border border-cv-border bg-black"
          style={natural ? { aspectRatio: `${shape!.w} / ${shape!.h}` } : undefined}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={`data:image/jpeg;base64,${result.preview_frame}`}
            alt="Live pipeline preview"
            className={places ? 'w-full h-full object-contain' : 'w-full object-cover'}
            style={places ? undefined : { aspectRatio: '16/9' }}
            onLoad={e => {
              const { naturalWidth: w, naturalHeight: h } = e.currentTarget;
              setShape(prev => (prev && prev.w === w && prev.h === h ? prev : { w, h }));
            }}
          />
          {marks && fit && (
            <svg viewBox={`0 0 ${fit.w} ${fit.h}`}
              style={{ position: 'absolute', left: fit.x, top: fit.y, width: fit.w, height: fit.h, pointerEvents: 'none' }}>
              <PlaceMarks marks={marks} width={fit.w} height={fit.h} unit={1} />
            </svg>
          )}
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
            <p className="text-cv-text text-sm font-medium">Analysing video...</p>
            <p className="text-cv-sub text-xs mt-1 max-w-xs mx-auto">
              The live preview appears as soon as the first frames are processed. Model loading can take a few seconds.
            </p>
          </div>
        </div>
      )}

      {/* Live counters under the preview */}
      {fd && (
        <div className={clsx('grid grid-cols-2 gap-3', places ? 'md:grid-cols-3' : 'md:grid-cols-4')}>
          {(places ? [
            { label: 'Video time',           value: `${fd.time_sec.toFixed(1)}s`,       color: 'text-cv-cyan'   },
            { label: 'People in view',       value: fd.people_now ?? 0,                 color: 'text-cv-accent' },
            { label: 'Tracks so far',        value: fd.tracks ?? 0,                     color: 'text-cv-text'   },
          ] : [
            { label: 'Video time',       value: `${fd.time_sec.toFixed(1)}s`,                  color: 'text-cv-cyan'   },
            { label: 'Looking now',      value: fd.looking_now ?? 0,                           color: 'text-cv-accent' },
            { label: 'Viewers so far',   value: fd.viewers ?? 0,                               color: 'text-cv-text'   },
            { label: 'Engaged / strong', value: `${fd.engaged ?? 0} / ${fd.strong ?? 0}`,      color: 'text-cv-amber'  },
          ]).map(({ label, value, color }) => (
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

/* ── Behaviour thresholds used for this analysis (read-only) ── */
function ThresholdValues({ glanceSec, engageSec, strongSec }: {
  glanceSec: number;
  engageSec: number;
  strongSec: number;
}) {
  return (
    <div className="glow-border bg-cv-card rounded-2xl p-5 space-y-3">
      <p className="text-xs font-mono text-cv-sub tracking-wider">THRESHOLDS USED</p>
      {[
        ['Looked from', glanceSec],
        ['Engaged from', engageSec],
        ['Strong from', strongSec],
      ].map(([label, v]) => (
        <div key={label} className="flex items-center justify-between text-sm text-cv-sub">
          {label}
          <span className="font-mono text-cv-text">{v} s</span>
        </div>
      ))}
      <p className="text-cv-sub text-[11px]">To try other thresholds, set them before uploading and run the analysis again.</p>
    </div>
  );
}

/* Mall places settings used for this analysis (read-only) */
function PlaceSettingsUsed({ staySec, stopSec }: { staySec: number; stopSec: number }) {
  return (
    <div className="glow-border bg-cv-card rounded-2xl p-5 space-y-3">
      <p className="text-xs font-mono text-cv-sub tracking-wider">SETTINGS USED</p>
      {[
        ['Entered after', staySec],
        ['Stopped after', stopSec],
      ].map(([label, v]) => (
        <div key={label} className="flex items-center justify-between text-sm text-cv-sub">
          {label}
          <span className="font-mono text-cv-text">{v} s</span>
        </div>
      ))}
      <p className="text-cv-sub text-[11px]">To try other values, set them before uploading and run the analysis again.</p>
    </div>
  );
}

/* ── Full results panel (shown after processing completes) ─── */
function ResultsPanel({ result, jobId, glanceSec, engageSec, strongSec, onChanged }: {
  result: AnalysisResult;
  jobId: string;
  glanceSec: number;
  engageSec: number;
  strongSec: number;
  onChanged: (updated: AnalysisResult) => void;
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

      <AnnotatedVideo result={result} />

      {result.mode === 'places' && result.places_result ? (
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
          <PlaceResults result={result.places_result} stats={stats} eventsUrl={result.events_url}
            jobId={jobId} canAdjust={result.can_adjust} onChanged={onChanged} />
        </motion.div>
      ) : (
        <>
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
            <MatchedLeads jobId={jobId} />
          </motion.div>

          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
            <ViewersTable
              viewers={result.viewers ?? []}
              glanceSec={glanceSec}
              engageSec={engageSec}
              strongSec={strongSec}
              csvUrl={result.viewers_url}
              jsonUrl={result.engaged_json_url}
              imageBase={`${BACKEND}/api/file/${jobId}/`}
              jobId={jobId}
            />
          </motion.div>
        </>
      )}

      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
        <UploadedVideo jobId={jobId} filename={result.filename} />
      </motion.div>
    </div>
  );
}

/* ── Main dashboard page ──────────────────────────────────── */
export default function DashboardPage() {
  const [file, setFile]               = useState<File | null>(null);
  const [jobId, setJobId]             = useState<string | null>(null);
  const [result, setResult]           = useState<AnalysisResult | null>(null);
  const [state, setState]             = useState<'idle'|'uploading'|'processing'|'done'|'error'>('idle');
  const [error, setError]             = useState<string | null>(null);
  const [backendOnline, setBackend]   = useState<boolean | null>(null);
  const [config, setConfig]           = useState<Settings>(DEFAULT_SETTINGS);
  const [mode, setMode]               = useState<AnalysisMode>('stand');
  const [drafts, setDrafts]           = useState<PlaceDraft[]>(() => [newDraft([])]);
  const [placeConfig, setPlaceConfig] = useState<PlaceSettings>(DEFAULT_PLACE_SETTINGS);
  const stopStream = useRef<(()=>void)|null>(null);

  useEffect(() => { checkBackendHealth().then(setBackend); }, []);

  // Keep glance <= engage <= strong whichever one the user moves
  const setSetting = useCallback((k: keyof Settings, v: number) => {
    setConfig(p => {
      const next = { ...p, [k]: v };
      if (k === 'glance_sec') { next.engage_sec = Math.max(next.engage_sec, v); next.strong_sec = Math.max(next.strong_sec, next.engage_sec); }
      if (k === 'engage_sec') { next.glance_sec = Math.min(next.glance_sec, v); next.strong_sec = Math.max(next.strong_sec, v); }
      if (k === 'strong_sec') { next.engage_sec = Math.min(next.engage_sec, v); next.glance_sec = Math.min(next.glance_sec, next.engage_sec); }
      return next;
    });
  }, []);

  const handleFile = useCallback((f: File) => {
    setFile(f); setResult(null); setState('idle'); setError(null);
    setDrafts([newDraft([])]);   // marks belong to one frame of one video
  }, []);

  const handleStart = async () => {
    if (!file) return;
    setState('uploading'); setError(null);
    try {
      const { job_id } = await uploadVideo(file, mode === 'places'
        ? { mode, places: toPlaces(drafts), ...placeConfig }
        : config);
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
    setFile(null); setJobId(null); setResult(null);
    setState('idle'); setError(null);
    setDrafts([newDraft([])]);
  };

  const places = mode === 'places';   // the mode switch is hidden once a video is processing, so this is the job's mode too
  const marksReady = draftsReady(drafts);
  const canStart = !!file && !!backendOnline && state !== 'uploading' && (!places || marksReady);
  const showSettings = state === 'idle' || state === 'uploading' || state === 'error';
  const eyebrow = { idle: 'NEW ANALYSIS', uploading: 'NEW ANALYSIS', processing: 'IN PROGRESS', done: 'RESULTS', error: 'NEW ANALYSIS' }[state];

  return (
    <AppShell>
      <div>
        {/* Header */}
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="mb-8 flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold tracking-wider text-cv-accent mb-2">{eyebrow}</p>
            <h1 className="font-display text-4xl text-cv-text mb-2">
              {state === 'done' ? 'Analysis complete' :
               state === 'processing' ? 'Processing...' :
               places ? 'Mall place analysis' : 'Visitor attention analysis'}
            </h1>
            <p className="text-cv-sub max-w-2xl">
              {state === 'idle'       && (file
                ? (places ? 'Mark the shops on a frame, adjust the settings if needed, then analyse the video.'
                          : 'Check the preview, adjust the settings if needed, then analyse the video.')
                : (places ? 'Upload a prerecorded video from a fixed mall camera, mark the shops once, and see who went into, left or stopped at each one.'
                          : 'Upload a prerecorded video from a camera at your product or advertisement to see who looked at it, and for how long.'))}
              {state === 'uploading'  && 'Uploading your video to the backend...'}
              {state === 'processing' && (places ? 'Detecting and tracking people frame by frame. Preview updates live.'
                                                  : 'Pose detection + ByteTrack running frame by frame. Preview updates live.')}
              {state === 'done'       && (places ? 'Entries, exits, stops, the order of visits, the annotated video and CSV are ready below.'
                                                  : 'Viewers, attention times, behaviour, the annotated video and CSV are ready below.')}
              {state === 'error'      && 'Something went wrong. See error details below.'}
            </p>
          </div>
          {state === 'done' && (
            <button onClick={handleReset}
              className="bg-cv-accent hover:bg-cv-accentL text-white px-4 py-2.5 rounded-xl text-sm font-semibold flex items-center gap-2 transition-colors flex-shrink-0">
              <Plus size={15} /> New video
            </button>
          )}
        </motion.div>

        <div className="grid xl:grid-cols-3 gap-6">
          {/* Main column — 2/3 width */}
          <div className="xl:col-span-2 space-y-5 min-w-0">
            {/* Upload / preview */}
            {(state === 'idle' || state === 'uploading' || state === 'error') && (
              <div className="space-y-5">
                {state !== 'uploading' && <ModeSwitch mode={mode} onChange={setMode} />}

                {!file && (
                  <>
                    <UploadZone onFile={handleFile} disabled={state === 'uploading'}
                      note={places ? 'Prerecorded footage from a fixed camera that sees the shop doors'
                                   : 'Prerecorded footage from a camera placed at the display'} />
                    <HowItWorks steps={places ? PLACES_STEPS : STAND_STEPS} />
                    <TipsAccordion tips={places ? PLACES_TIPS : STAND_TIPS} />
                  </>
                )}

                {file && (
                  <>
                    <div className="glow-border bg-cv-card p-4 flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 bg-cv-accent/10 rounded-lg flex items-center justify-center">
                          <Film size={17} className="text-cv-accent" />
                        </div>
                        <div>
                          <p className="text-cv-text text-sm font-medium">{file.name}</p>
                          <p className="text-cv-sub text-xs font-mono">{(file.size/1e6).toFixed(1)} MB · {file.type}</p>
                        </div>
                      </div>
                      <button onClick={handleReset} title="Remove video" className="text-cv-sub hover:text-cv-red transition-colors"><X size={17} /></button>
                    </div>

                    {places
                      ? <PlaceMarker key={`${file.name}-${file.size}-${file.lastModified}`} source={file} drafts={drafts} onChange={setDrafts} />
                      : <VideoPreview file={file} hint="Preview. Best results: camera at the display, facing the people who approach." />}
                    <StartButton onStart={handleStart} canStart={canStart}
                      starting={state === 'uploading'} backendOnline={backendOnline}
                      note={places && !marksReady ? 'Mark a door line and the inside for every shop, with a different name each, to continue.' : undefined} />
                  </>
                )}
              </div>
            )}

            {/* LIVE PREVIEW during processing */}
            <AnimatePresence>
              {state === 'processing' && (
                <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
                  <LivePreview result={result ?? {} as AnalysisResult} marks={places ? toPlaces(drafts) : undefined} />
                </motion.div>
              )}
            </AnimatePresence>

            {/* FULL RESULTS after done */}
            <AnimatePresence>
              {state === 'done' && result && jobId && (
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                  <ResultsPanel
                    result={result} jobId={jobId}
                    glanceSec={config.glance_sec} engageSec={config.engage_sec} strongSec={config.strong_sec}
                    onChanged={setResult}
                  />
                </motion.div>
              )}
            </AnimatePresence>

            {/* Error */}
            {state === 'error' && (
              <div className="glow-border bg-cv-red/5 border-cv-red/30 p-5 flex items-start gap-4">
                <AlertTriangle size={20} className="text-cv-red flex-shrink-0 mt-0.5" />
                <div className="flex-1">
                  <p className="font-semibold text-cv-text mb-1">Processing failed</p>
                  <p className="text-cv-sub text-sm font-mono whitespace-pre-wrap">{error}</p>
                </div>
              </div>
            )}
          </div>

          {/* Right column: settings before analysis, thresholds + analytics after */}
          <div className={clsx('space-y-4 min-w-0', state === 'done' && 'xl:sticky xl:top-6 xl:self-start xl:max-h-[calc(100vh-3rem)] xl:overflow-y-auto xl:p-1 xl:-m-1')}>
            {showSettings && (places
              ? <PlaceSettingsPanel config={placeConfig} onChange={(k, v) => setPlaceConfig(p => ({ ...p, [k]: v }))} />
              : <SettingsPanel config={config} onChange={setSetting} onPreset={setConfig} />
            )}

            {state === 'processing' && (places
              ? <PlaceSettingsUsed staySec={placeConfig.stay_sec} stopSec={placeConfig.stop_sec} />
              : <ThresholdValues glanceSec={config.glance_sec} engageSec={config.engage_sec} strongSec={config.strong_sec} />
            )}

            {state === 'done' && result && (places ? (
              <PlaceSettingsUsed staySec={result.stats?.stay_sec ?? placeConfig.stay_sec}
                stopSec={result.stats?.stop_sec ?? placeConfig.stop_sec} />
            ) : (
              <>
                <ThresholdValues
                  glanceSec={config.glance_sec} engageSec={config.engage_sec} strongSec={config.strong_sec}
                />
                <SummaryCards
                  compact
                  viewers={result.viewers ?? []}
                  glanceSec={config.glance_sec} engageSec={config.engage_sec} strongSec={config.strong_sec}
                  durationSec={result.stats?.duration_sec ?? 0}
                  ignored={result.stats?.ignored ?? 0}
                />
              </>
            ))}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
