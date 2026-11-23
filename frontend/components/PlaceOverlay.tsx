'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, Eye, EyeOff, Loader2, Play, Tag } from 'lucide-react';
import clsx from 'clsx';
import type { Place } from '@/lib/api';
import { PlaceMarks } from '@/components/PlaceMarks';
import { fitRect, type Rect } from '@/lib/fit';

/* The annotated video with the shops drawn over it by the page, so they can be switched off and never cover
   the picture. The player shows the video with bars around it when its shape differs from the box, so the
   marks are placed on the picture itself, not on the box. */
export function PlaceOverlay({ src, places }: { src: string; places: Place[] }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [rect, setRect] = useState<Rect | null>(null);
  const [shops, setShops] = useState(true);
  const [labels, setLabels] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(false);

  const measure = useCallback(() => {
    const box = wrapRef.current;
    const v = videoRef.current;
    if (!box || !v) return;
    setRect(fitRect({ w: box.clientWidth, h: box.clientHeight }, { w: v.videoWidth, h: v.videoHeight }));
  }, []);

  useEffect(() => { setLoaded(false); setError(false); setRect(null); }, [src]);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [measure]);

  const toggle = (on: boolean, set: (v: boolean) => void, label: string, Icon: typeof Eye, Off: typeof Eye) => (
    <button onClick={() => set(!on)} aria-pressed={on}
      className={clsx('px-3 py-1 rounded-full text-xs font-medium border flex items-center gap-1.5 transition-colors',
        on ? 'bg-cv-accent/[0.07] border-cv-accent text-cv-text' : 'bg-cv-card border-cv-border text-cv-sub hover:border-cv-accent/40')}>
      {on ? <Icon size={12} /> : <Off size={12} />} {label}
    </button>
  );

  return (
    <div>
      <div className="px-5 py-2.5 flex items-center gap-2 border-b border-cv-border">
        <span className="text-cv-sub text-xs font-mono mr-1">DRAWN OVER THE VIDEO</span>
        {toggle(shops, setShops, 'Shops', Eye, EyeOff)}
        {toggle(labels, setLabels, 'Labels', Tag, Tag)}
      </div>
      <div ref={wrapRef} className="relative bg-black" style={{ aspectRatio: '16/9' }}>
        {!loaded && !error && (
          <div className="absolute inset-0 flex items-center justify-center bg-cv-surface">
            <Loader2 size={24} className="text-cv-accent animate-spin" />
          </div>
        )}
        {error && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-cv-surface gap-3 p-6">
            <AlertTriangle size={26} className="text-cv-amber" />
            <p className="text-cv-text font-semibold text-sm">Video preview unavailable</p>
            <a href={src} target="_blank" rel="noopener noreferrer"
              className="flex items-center gap-2 bg-cv-accent text-white text-xs font-semibold px-4 py-2 rounded-xl">
              <Play size={12} fill="currentColor" /> Open in new tab
            </a>
          </div>
        )}
        <video ref={videoRef} src={src} controls autoPlay loop muted playsInline
          className="w-full h-full object-contain" style={{ display: error ? 'none' : 'block' }}
          onLoadedMetadata={measure} onLoadedData={() => { measure(); setLoaded(true); }} onError={() => setError(true)} />
        {rect && shops && (
          <svg viewBox={`0 0 ${rect.w} ${rect.h}`}
            style={{ position: 'absolute', left: rect.x, top: rect.y, width: rect.w, height: rect.h, pointerEvents: 'none' }}>
            <PlaceMarks marks={places} width={rect.w} height={rect.h} unit={1} labels={labels} />
          </svg>
        )}
      </div>
    </div>
  );
}
