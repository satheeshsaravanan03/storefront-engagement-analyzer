'use client';

import { useEffect, useRef, useState } from 'react';
import { Play, Pause, Trash2, Square } from 'lucide-react';
import type { Zone } from '@/lib/api';

const clamp = (v: number) => Math.min(1, Math.max(0, v));
const norm = (z: Zone): Zone => ({
  x1: Math.min(z.x1, z.x2), y1: Math.min(z.y1, z.y2),
  x2: Math.max(z.x1, z.x2), y2: Math.max(z.y1, z.y2),
});

/* Local video preview + drag-to-draw storefront rectangle.
   The zone is stored as ratios (0–1) of the frame, so it is independent
   of the on-screen size and maps directly onto the real video frame. */
export function ZoneSelector({ file, zone, onChange }: {
  file: File;
  zone: Zone | null;
  onChange: (z: Zone | null) => void;
}) {
  const [url, setUrl]         = useState<string | null>(null);
  const [aspect, setAspect]   = useState(16 / 9);
  const [duration, setDur]    = useState(0);
  const [time, setTime]       = useState(0);
  const [playing, setPlaying] = useState(false);
  const [anchor, setAnchor]   = useState<{ x: number; y: number } | null>(null);
  const [draft, setDraft]     = useState<Zone | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const boxRef   = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const u = URL.createObjectURL(file);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [file]);

  const point = (e: React.PointerEvent) => {
    const r = boxRef.current!.getBoundingClientRect();
    return { x: clamp((e.clientX - r.left) / r.width), y: clamp((e.clientY - r.top) / r.height) };
  };

  const onDown = (e: React.PointerEvent) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    const p = point(e);
    setAnchor(p);
    setDraft({ x1: p.x, y1: p.y, x2: p.x, y2: p.y });
  };
  const onMove = (e: React.PointerEvent) => {
    if (!anchor) return;
    const p = point(e);
    setDraft({ x1: anchor.x, y1: anchor.y, x2: p.x, y2: p.y });
  };
  const onUp = () => {
    if (draft) {
      const z = norm(draft);
      if (z.x2 - z.x1 > 0.02 && z.y2 - z.y1 > 0.02) onChange(z);
    }
    setAnchor(null);
    setDraft(null);
  };

  const togglePlay = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) { v.play(); } else { v.pause(); }
  };

  const shown = draft ? norm(draft) : zone;

  return (
    <div className="glow-border bg-cv-card rounded-2xl overflow-hidden">
      <div className="px-5 py-3 border-b border-cv-border flex items-center gap-2">
        <Square size={14} className="text-cv-accent" />
        <span className="font-semibold text-cv-text text-sm">Video preview &amp; storefront zone</span>
        <span className="text-cv-sub text-xs font-mono ml-auto">
          {zone ? 'Zone set — drag again to redraw' : 'Drag on the video to mark the area in front of the store'}
        </span>
      </div>

      <div ref={boxRef} className="relative bg-black select-none" style={{ aspectRatio: String(aspect) }}>
        {url && (
          <video
            ref={videoRef}
            src={url}
            muted
            playsInline
            preload="metadata"
            className="absolute inset-0 w-full h-full"
            onLoadedMetadata={e => {
              const v = e.currentTarget;
              if (v.videoWidth && v.videoHeight) setAspect(v.videoWidth / v.videoHeight);
              setDur(v.duration || 0);
            }}
            onTimeUpdate={e => setTime(e.currentTarget.currentTime)}
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
          />
        )}

        {/* Drawing surface */}
        <div
          className="absolute inset-0 cursor-crosshair touch-none"
          onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp}
        >
          {shown && (
            <div
              className="absolute border-2 border-cv-accent bg-cv-accent/20 pointer-events-none"
              style={{
                left: `${shown.x1 * 100}%`, top: `${shown.y1 * 100}%`,
                width: `${(shown.x2 - shown.x1) * 100}%`, height: `${(shown.y2 - shown.y1) * 100}%`,
              }}
            >
              <span className="absolute -top-5 left-0 text-[10px] font-mono text-cv-accent bg-black/70 px-1.5 rounded">
                STOREFRONT ZONE
              </span>
            </div>
          )}
        </div>
      </div>

      <div className="px-5 py-3 flex items-center gap-3 border-t border-cv-border">
        <button onClick={togglePlay} className="text-cv-sub hover:text-cv-text transition-colors" aria-label={playing ? 'Pause' : 'Play'}>
          {playing ? <Pause size={16} /> : <Play size={16} />}
        </button>
        <input
          type="range" min={0} max={duration || 1} step={0.1} value={time}
          onChange={e => { if (videoRef.current) videoRef.current.currentTime = parseFloat(e.target.value); }}
          className="flex-1 h-1.5 bg-cv-border rounded-full appearance-none cursor-pointer accent-cv-accent"
        />
        <span className="text-cv-sub text-xs font-mono w-24 text-right">
          {time.toFixed(1)}s / {duration.toFixed(1)}s
        </span>
        <button
          onClick={() => onChange(null)} disabled={!zone}
          className="flex items-center gap-1.5 text-xs font-mono text-cv-sub hover:text-cv-red disabled:opacity-40 disabled:hover:text-cv-sub transition-colors"
        >
          <Trash2 size={12} /> Clear
        </button>
      </div>
    </div>
  );
}
