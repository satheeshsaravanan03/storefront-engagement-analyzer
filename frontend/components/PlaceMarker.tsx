'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  AlertTriangle, ArrowLeftRight, Check, DoorOpen, Footprints, Loader2, MapPin, Maximize2, Plus, Trash2, Undo2, ZoomIn, ZoomOut,
} from 'lucide-react';
import clsx from 'clsx';
import type { Place, Point } from '@/lib/api';
import { PlaceMarks, SHOP_COLORS, type ShopMark } from '@/components/PlaceMarks';

/* A shop while it is being marked: any part may still be missing. */
export type PlaceDraft = ShopMark;

// Same limits as backend/places.py (MAX_PLACES, MAX_FRONT_POINTS, MIN_DOOR_LEN, MIN_INSIDE_DIST, MIN_FRONT_AREA),
// so a bad mark is caught here and not after a large video has been uploaded
const MAX_SHOPS = 8;
const MAX_FRONT_POINTS = 32;
const MIN_DOOR_LEN = 0.02;
const MIN_INSIDE_DIST = 0.01;
const MIN_FRONT_AREA = 1e-4;
const MAX_ZOOM = 8;

const clamp01 = (v: number) => Math.min(1, Math.max(0, v));

/* The next free "Shop N" name. */
export function newDraft(existing: PlaceDraft[]): PlaceDraft {
  const used = new Set(existing.map(d => d.name.trim().toLowerCase()));
  let n = existing.length + 1;
  while (used.has(`shop ${n}`)) n++;
  return { name: `Shop ${n}`, door: [], inside: null, front: [] };
}

function polygonArea(poly: Point[]): number {
  let s = 0;
  poly.forEach((p, i) => { const q = poly[(i + 1) % poly.length]; s += p[0] * q[1] - q[0] * p[1]; });
  return Math.abs(s) / 2;
}

/* What is still wrong with a shop, or null when it is ready. */
export function draftProblem(d: PlaceDraft): string | null {
  if (d.name.trim() === '') return 'needs a name';
  if (d.door.length < 2 || !d.inside) return 'needs a door line and the inside';
  const [a, b] = d.door;
  const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
  if (len < MIN_DOOR_LEN) return 'the door line is too short';
  const away = Math.abs((b[0] - a[0]) * (d.inside[1] - a[1]) - (b[1] - a[1]) * (d.inside[0] - a[0])) / len;
  if (away < MIN_INSIDE_DIST) return 'the inside pin is on the door line';
  if (d.front.length > 0 && d.front.length < 3) return 'the front area needs 3 points, or clear it';
  if (d.front.length >= 3 && polygonArea(d.front) < MIN_FRONT_AREA) return 'the front area is too small';
  return null;
}

export const isDraftReady = (d: PlaceDraft) => draftProblem(d) === null;

export function draftsReady(ds: PlaceDraft[]): boolean {
  const names = ds.map(d => d.name.trim().toLowerCase());
  return ds.length > 0 && ds.every(isDraftReady) && new Set(names).size === names.length;
}

/* Only call this when draftsReady(ds). */
export const toPlaces = (ds: PlaceDraft[]): Place[] => ds.map(d => ({
  name: d.name.trim(),
  door: [d.door[0], d.door[1]],
  inside: d.inside as Point,
  front: d.front,
}));

/* Marks that were used for a job, ready to be edited again. */
export const toDrafts = (places: Place[]): PlaceDraft[] => places.map(p => ({
  name: p.name, door: [...p.door], inside: p.inside, front: [...p.front],
}));

type Tool = 'door' | 'inside' | 'front' | null;

/* The step a shop is waiting for, so the editor can carry on where the user left off. */
const nextStep = (d?: PlaceDraft): Tool => (!d || d.door.length < 2 ? 'door' : d.inside ? null : 'inside');

/* The pin moved to the other side of the door, the same distance away. */
function flipped(d: PlaceDraft): Point | null {
  if (d.door.length < 2 || !d.inside) return d.inside;
  const [a, b] = d.door;
  return [clamp01(a[0] + b[0] - d.inside[0]), clamp01(a[1] + b[1] - d.inside[1])];
}

type Drag = { kind: 'door' | 'pin' | 'front'; idx: number; moved: boolean };

/* Mark the shops on one frame of the video. Door line: two points on the floor at the doorway. Pin: one click
   inside the shop; it sets which side is in, which way people walk in, and how deep the shop area is, and the
   shaded area is exactly what the analysis uses. Front area: optional. Everything is stored as fractions of the
   frame. The video is a file the user chose, or a URL (to adjust the marks of a finished job). */
export function PlaceMarker({ source, drafts, onChange }: {
  source: File | string;
  drafts: PlaceDraft[];
  onChange: (d: PlaceDraft[]) => void;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const frameRef = useRef<HTMLCanvasElement | null>(null);   // the captured frame, without the marks
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const loupeRef = useRef<HTMLCanvasElement>(null);
  const press = useRef<{ x: number; y: number; vx: number; vy: number; moved: boolean } | null>(null);
  const drag = useRef<Drag | null>(null);
  const history = useRef<PlaceDraft[][]>([]);

  const [url, setUrl] = useState<string | null>(null);
  const [duration, setDuration] = useState(0);
  const [time, setTime] = useState(0);
  const [frameNo, setFrameNo] = useState(0);                       // goes up when a frame was captured, to redraw
  const [failed, setFailed] = useState(false);
  const [size, setSize] = useState({ w: 16, h: 9 });               // the frame's size in pixels, once there is one
  const [box, setBox] = useState(0);                               // the picture's width on screen at zoom 1
  const [view, setView] = useState({ z: 1, x: 0, y: 0 });
  const [cursor, setCursor] = useState<{ p: Point; sx: number; sy: number } | null>(null);
  const [picked, setActive] = useState(0);
  const active = Math.min(picked, drafts.length - 1);          // undo can remove the shop that was being edited
  const [tool, setTool] = useState<Tool>(() => nextStep(drafts[0]));   // the marks outlive this component
  const [canUndo, setCanUndo] = useState(false);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    const u = typeof source === 'string' ? source : URL.createObjectURL(source);
    setUrl(u); setFailed(false); setFrameNo(0); setDuration(0); setTime(0); setView({ z: 1, x: 0, y: 0 });
    history.current = []; setCanUndo(false);
    return () => { if (typeof source !== 'string') URL.revokeObjectURL(u); };
  }, [source]);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setBox(el.clientWidth));
    ro.observe(el);
    setBox(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  const capture = useCallback(() => {
    const v = videoRef.current;
    if (!v || !v.videoWidth) return;
    if (!frameRef.current) frameRef.current = document.createElement('canvas');
    const c = frameRef.current;
    c.width = Math.min(v.videoWidth, 1920);
    c.height = Math.round((c.width * v.videoHeight) / v.videoWidth);
    c.getContext('2d')?.drawImage(v, 0, 0, c.width, c.height);
    setSize({ w: c.width, h: c.height });
    setFrameNo(n => n + 1);
  }, []);

  useEffect(() => {
    const cv = canvasRef.current;
    const fr = frameRef.current;
    if (!cv || !fr) return;
    cv.width = fr.width;
    cv.height = fr.height;
    cv.getContext('2d')?.drawImage(fr, 0, 0);
  }, [frameNo]);

  const seek = (t: number) => {
    setTime(t);
    if (videoRef.current) videoRef.current.currentTime = t;   // 'seeked' captures the new frame
  };

  const height = (box * size.h) / size.w;                       // the picture's height on screen at zoom 1
  const unit = box > 0 ? size.w / (box * view.z) : 1;           // frame pixels per screen pixel

  const clampView = useCallback((x: number, y: number, z: number) => ({
    z, x: Math.min(0, Math.max(box - box * z, x)), y: Math.min(0, Math.max(height - height * z, y)),
  }), [box, height]);

  const zoomAt = useCallback((sx: number, sy: number, factor: number) => {
    setView(v => {
      const z = Math.min(MAX_ZOOM, Math.max(1, v.z * factor));
      const k = z / v.z;
      return clampView(sx - (sx - v.x) * k, sy - (sy - v.y) * k, z);
    });
  }, [clampView]);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * 0.0015));
    };
    el.addEventListener('wheel', onWheel, { passive: false });   // React's own wheel handler cannot stop the page scrolling
    return () => el.removeEventListener('wheel', onWheel);
  }, [zoomAt]);

  /* A point of the screen as a fraction of the frame */
  const toPoint = (e: { clientX: number; clientY: number }): Point => {
    const r = wrapRef.current!.getBoundingClientRect();
    return [clamp01((e.clientX - r.left - view.x) / (box * view.z)), clamp01((e.clientY - r.top - view.y) / (height * view.z))];
  };

  const commit = (next: PlaceDraft[]) => {
    history.current = [...history.current.slice(-49), drafts];
    setCanUndo(true);
    onChange(next);
  };
  const undo = () => {
    const prev = history.current.pop();
    if (prev) onChange(prev);
    setCanUndo(history.current.length > 0);
  };
  const edit = (i: number, fn: (d: PlaceDraft) => PlaceDraft) => drafts.map((d, k) => (k === i ? fn(d) : d));

  const selectTool = (t: Exclude<Tool, null>, i = active) => {
    setActive(i);
    setTool(t);
    // a door line is drawn again from scratch, and the pin belongs to one door line
    if (t === 'door' && drafts[i].door.length === 2) commit(edit(i, d => ({ ...d, door: [], inside: null })));
  };

  const place = (p: Point) => {
    const d = drafts[active];
    if (!tool || !d) return;
    if (tool === 'door') {
      const door = [...d.door, p].slice(0, 2);
      commit(edit(active, x => ({ ...x, door })));
      if (door.length === 2) setTool('inside');
    } else if (tool === 'inside') {
      commit(edit(active, x => ({ ...x, inside: p })));
      setTool(null);
    } else if (d.front.length < MAX_FRONT_POINTS) {
      commit(edit(active, x => ({ ...x, front: [...x.front, p] })));
    }
  };

  const startDrag = (e: React.PointerEvent, kind: Drag['kind'], idx: number) => {
    e.stopPropagation();
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { kind, idx, moved: false };
    setDragging(true);
  };

  const moveHandle = (p: Point) => {
    const dr = drag.current;
    if (!dr) return;
    if (!dr.moved) {                                   // a click on a point is not a step to undo
      dr.moved = true;
      history.current = [...history.current.slice(-49), drafts];
      setCanUndo(true);
    }
    onChange(edit(active, d => dr.kind === 'door' ? { ...d, door: d.door.map((q, k) => (k === dr.idx ? p : q)) }
      : dr.kind === 'pin' ? { ...d, inside: p }
      : { ...d, front: d.front.map((q, k) => (k === dr.idx ? p : q)) }));
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    press.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, moved: false };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const r = wrapRef.current!.getBoundingClientRect();
    const here = { p: toPoint(e), sx: e.clientX - r.left, sy: e.clientY - r.top };
    if (drag.current) { moveHandle(here.p); setCursor(here); return; }
    const pr = press.current;
    if (pr) {
      if (!pr.moved && Math.hypot(e.clientX - pr.x, e.clientY - pr.y) > 4) pr.moved = true;
      if (pr.moved) setView(clampView(pr.vx + e.clientX - pr.x, pr.vy + e.clientY - pr.y, view.z));   // a drag pans
      return;
    }
    setCursor(here);
  };
  const onPointerEnd = () => { press.current = null; drag.current = null; setDragging(false); };
  const onPointerUp = (e: React.PointerEvent) => {
    const pr = press.current;
    onPointerEnd();
    if (pr && !pr.moved) place(toPoint(e));                                                          // a click places a point
  };

  const onKey = (e: KeyboardEvent) => {
    const tag = (e.target as HTMLElement).tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA') return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); undo(); }
    else if ((e.key === 'Escape' || e.key === 'Enter') && tool) { e.preventDefault(); setTool(null); }
    else if (e.key === '1') selectTool('door');
    else if (e.key === '2' && drafts[active]?.door.length === 2) selectTool('inside');
    else if (e.key === '3') selectTool('front');
  };
  const keyRef = useRef(onKey);
  keyRef.current = onKey;
  useEffect(() => {
    const listener = (e: KeyboardEvent) => keyRef.current(e);
    window.addEventListener('keydown', listener, true);          // capture: the editor sees a key before the window around it
    return () => window.removeEventListener('keydown', listener, true);
  }, []);

  // the picture can change size (a window resize): keep it from sliding out of its box
  useEffect(() => { setView(v => clampView(v.x, v.y, v.z)); }, [clampView]);

  /* The magnifier: a close-up of the frame around the pointer, so a click can be exact */
  useEffect(() => {
    const lc = loupeRef.current;
    const fr = frameRef.current;
    const ctx = lc?.getContext('2d');
    if (!lc || !fr || !ctx || !cursor || !(tool || dragging)) return;
    const span = 40;
    const cx = cursor.p[0] * fr.width;
    const cy = cursor.p[1] * fr.height;
    ctx.clearRect(0, 0, lc.width, lc.height);
    ctx.drawImage(fr, cx - span / 2, cy - span / 2, span, span, 0, 0, lc.width, lc.height);
    const m = lc.width / 2;
    ctx.lineWidth = 3; ctx.strokeStyle = 'rgba(0,0,0,0.55)';
    ctx.beginPath(); ctx.moveTo(m, 6); ctx.lineTo(m, m - 8); ctx.moveTo(m, m + 8); ctx.lineTo(m, lc.height - 6);
    ctx.moveTo(6, m); ctx.lineTo(m - 8, m); ctx.moveTo(m + 8, m); ctx.lineTo(lc.width - 6, m); ctx.stroke();
    ctx.lineWidth = 1; ctx.strokeStyle = '#fff'; ctx.stroke();
  }, [cursor, tool, dragging, frameNo]);

  const cur = drafts[active];
  const problem = cur ? draftProblem(cur) : null;
  const color = SHOP_COLORS[active % SHOP_COLORS.length];

  // what the next click would do, drawn before it is made
  const shown = drafts.map((d, i): PlaceDraft => {
    if (i !== active || !cursor) return d;
    if (tool === 'door' && d.door.length === 1) return { ...d, door: [d.door[0], cursor.p] };
    if (tool === 'inside' && d.door.length === 2) return { ...d, inside: cursor.p };
    if (tool === 'front' && d.front.length >= 2) return { ...d, front: [...d.front, cursor.p] };
    return d;
  });

  const hint =
    tool === 'door'   ? (cur?.door.length ? 'Click the other end of the door line, on the floor at the doorway' : 'Click one end of the door line, on the floor where the shop meets the walkway') :
    tool === 'inside' ? 'Click inside the shop, the way people walk in. The shaded area is what counts as inside' :
    tool === 'front'  ? 'Click the corners of the floor area in front of the shop, then press Done' :
    'Drag a point to adjust it. Scroll to zoom. Esc stops drawing';

  const step = (t: Exclude<Tool, null>, label: string, Icon: typeof DoorOpen, done: boolean, off = false) => (
    <button key={t} onClick={() => selectTool(t)} disabled={off}
      className={clsx('px-3 py-1.5 rounded-lg text-xs font-semibold border flex items-center gap-1.5 transition-colors disabled:opacity-40 disabled:cursor-not-allowed',
        tool === t ? 'bg-cv-accent text-white border-cv-accent' : 'bg-cv-card text-cv-text border-cv-border hover:border-cv-accent/40')}>
      <Icon size={13} /> {label} {done && <Check size={12} className={tool === t ? 'text-white' : 'text-cv-green'} />}
    </button>
  );
  const tb = 'p-1.5 rounded-md text-cv-text hover:bg-cv-black disabled:opacity-35 disabled:cursor-not-allowed transition-colors';

  const handle = (p: Point, kind: Drag['kind'], idx: number) => {
    const [x, y] = [p[0] * size.w, p[1] * size.h];
    return (
      <g key={`${kind}${idx}`} style={{ pointerEvents: tool ? 'none' : 'all', cursor: 'grab' }} onPointerDown={e => startDrag(e, kind, idx)}>
        <circle cx={x} cy={y} r={16 * unit} fill="transparent" />
        <circle cx={x} cy={y} r={kind === 'pin' ? 7 * unit : 5.5 * unit} fill="#fff" stroke={color} strokeWidth={2 * unit} />
      </g>
    );
  };

  return (
    <div className="glow-border bg-cv-card rounded-2xl overflow-hidden">
      <video ref={videoRef} src={url ?? undefined} muted playsInline preload="auto"
        className="absolute h-px w-px opacity-0 pointer-events-none"
        onLoadedMetadata={e => setDuration(e.currentTarget.duration || 0)}
        onLoadedData={capture} onSeeked={capture} onError={() => setFailed(true)} />

      {/* the shops */}
      <div className="px-4 pt-4 pb-3 flex flex-wrap items-center gap-2">
        {drafts.map((d, i) => (
          <button key={i} onClick={() => { setActive(i); setTool(nextStep(d)); }}
            className={clsx('pl-2.5 pr-3 py-1.5 rounded-full text-sm font-medium border flex items-center gap-2 transition-colors',
              i === active ? 'bg-cv-accent/[0.07] border-cv-accent text-cv-text' : 'bg-cv-card border-cv-border text-cv-sub hover:border-cv-accent/40')}>
            <span className="w-2.5 h-2.5 rounded-full" style={{ background: SHOP_COLORS[i % SHOP_COLORS.length] }} />
            {d.name.trim() || 'Shop'}
            {isDraftReady(d) && <Check size={13} className="text-cv-green" />}
          </button>
        ))}
        <button onClick={() => { commit([...drafts, newDraft(drafts)]); setActive(drafts.length); setTool('door'); }}
          disabled={drafts.length >= MAX_SHOPS}
          className="px-3 py-1.5 rounded-full text-sm font-medium text-cv-accent border border-dashed border-cv-accent/40 hover:bg-cv-accent/5 flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed">
          <Plus size={13} /> Add shop
        </button>
      </div>

      {cur && (
        <div className="px-4 pb-3 flex flex-wrap items-center gap-2">
          <input value={cur.name} maxLength={40} aria-label="Shop name"
            onChange={e => onChange(edit(active, x => ({ ...x, name: e.target.value })))}
            className="w-40 bg-cv-surface border border-cv-border rounded-lg px-3 py-1.5 text-sm text-cv-text focus:outline-none focus:border-cv-accent" />
          {step('door', 'Door', DoorOpen, cur.door.length === 2)}
          {step('inside', 'Inside', MapPin, cur.inside !== null, cur.door.length < 2)}
          {step('front', 'Front', Footprints, cur.front.length >= 3)}
          {tool === 'front' && (
            <button onClick={() => setTool(null)}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-cv-accent text-cv-accent hover:bg-cv-accent/5">Done</button>
          )}
          {cur.front.length > 0 && tool !== 'front' && (
            <button onClick={() => commit(edit(active, x => ({ ...x, front: [] })))}
              className="px-2 py-1.5 text-xs text-cv-sub hover:text-cv-red">Clear front</button>
          )}
          <button onClick={() => commit(edit(active, x => ({ ...x, inside: flipped(x) })))} disabled={!cur.inside}
            title="Move the pin to the other side of the door"
            className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-cv-border text-cv-text hover:border-cv-accent/40 flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed">
            <ArrowLeftRight size={13} /> Flip
          </button>
          <button onClick={() => { const rest = drafts.filter((_, k) => k !== active); commit(rest.length ? rest : [newDraft([])]); setActive(0); setTool(null); }}
            aria-label={`Remove ${cur.name}`} className="p-1.5 rounded-lg text-cv-sub hover:text-cv-red hover:bg-cv-red/10 transition-colors">
            <Trash2 size={15} />
          </button>
        </div>
      )}

      {/* the picture */}
      <div ref={wrapRef} onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp}
        onPointerLeave={() => setCursor(null)} onPointerCancel={onPointerEnd}
        className={clsx('relative bg-black overflow-hidden touch-none select-none', tool ? 'cursor-crosshair' : 'cursor-grab')}
        style={box > 0 && frameNo > 0 ? { height } : { aspectRatio: '16/9' }}>
        {frameNo > 0 && (
          <div className="absolute left-0 top-0"
            style={{ width: box, height, transform: `translate(${view.x}px, ${view.y}px) scale(${view.z})`, transformOrigin: '0 0' }}>
            <canvas ref={canvasRef} className="block w-full h-full" />
            <svg viewBox={`0 0 ${size.w} ${size.h}`} className="absolute inset-0 w-full h-full" style={{ pointerEvents: 'none' }}>
              <PlaceMarks marks={shown} width={size.w} height={size.h} unit={unit} active={active} />
              {cur && (
                <g>
                  {cur.door.map((p, k) => handle(p, 'door', k))}
                  {cur.inside && handle(cur.inside, 'pin', 0)}
                  {cur.front.map((p, k) => handle(p, 'front', k))}
                </g>
              )}
            </svg>
          </div>
        )}

        {frameNo === 0 && !failed && (
          <div className="absolute inset-0 flex items-center justify-center gap-2 text-white/70 text-xs font-mono">
            <Loader2 size={14} className="animate-spin" /> Reading a frame...
          </div>
        )}
        {failed && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 px-6 text-center bg-cv-surface">
            <AlertTriangle size={26} className="text-cv-amber" />
            <p className="text-cv-text font-semibold text-sm">This browser cannot read this video</p>
            <p className="text-cv-sub text-xs max-w-sm">Marking needs a frame from the file. Use an H.264 MP4 instead.</p>
          </div>
        )}

        {frameNo > 0 && (
          <>
            <div className="absolute top-3 right-3 flex items-center gap-0.5 rounded-xl bg-cv-card/90 backdrop-blur px-1 py-1 shadow-sm"
              onPointerDown={e => e.stopPropagation()} onPointerUp={e => e.stopPropagation()}>
              <button className={tb} aria-label="Zoom out" onClick={() => zoomAt(box / 2, height / 2, 1 / 1.5)}><ZoomOut size={15} /></button>
              <span className="w-10 text-center text-[11px] font-mono text-cv-sub">{Math.round(view.z * 100)}%</span>
              <button className={tb} aria-label="Zoom in" onClick={() => zoomAt(box / 2, height / 2, 1.5)}><ZoomIn size={15} /></button>
              <button className={tb} aria-label="Reset the view" onClick={() => setView({ z: 1, x: 0, y: 0 })}><Maximize2 size={14} /></button>
              <span className="w-px h-4 bg-cv-border mx-1" />
              <button className={tb} aria-label="Undo" title="Undo (Ctrl+Z)" onClick={undo} disabled={!canUndo}><Undo2 size={15} /></button>
            </div>

            {cur && (
              <div className={clsx('absolute top-3 left-3 max-w-[55%] truncate rounded-full px-3 py-1 text-[11px] font-mono text-white pointer-events-none',
                problem === null ? 'bg-cv-green/90' : problem.startsWith('needs') ? 'bg-black/60' : 'bg-cv-amber')}>
                {cur.name.trim() || 'Shop'}: {problem ?? 'ready'}
              </div>
            )}

            <div className="absolute bottom-3 left-1/2 -translate-x-1/2 max-w-[92%] rounded-full bg-black/70 backdrop-blur px-4 py-1.5 text-center text-xs text-white pointer-events-none">
              {hint}
            </div>

            {cursor && (tool || dragging) && (
              <canvas ref={loupeRef} width={120} height={120} aria-hidden
                className="absolute rounded-full border-2 border-white shadow-lg pointer-events-none"
                style={{
                  width: 120, height: 120,
                  left: Math.min(Math.max(cursor.sx + 22, 4), box - 124),
                  top: cursor.sy - 142 < 4 ? cursor.sy + 22 : cursor.sy - 142,
                }} />
            )}
          </>
        )}
      </div>

      {duration > 0 && (
        <div className="px-4 py-2.5 flex items-center gap-3 border-t border-cv-border">
          <span className="text-cv-sub text-xs font-mono whitespace-nowrap">Frame at {time.toFixed(1)} s</span>
          <input type="range" min={0} max={Math.max(duration - 0.1, 0)} step={0.1} value={time}
            onChange={e => seek(parseFloat(e.target.value))} className="cv-range w-full" aria-label="Frame to mark on"
            style={{ background: `linear-gradient(to right, #4F46E5 ${(time / Math.max(duration - 0.1, 0.1)) * 100}%, #E2E4EE ${(time / Math.max(duration - 0.1, 0.1)) * 100}%)` }} />
        </div>
      )}
    </div>
  );
}
