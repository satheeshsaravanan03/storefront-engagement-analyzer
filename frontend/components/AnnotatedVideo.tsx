'use client';

import { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { AlertTriangle, Download, Film, Loader2, Play } from 'lucide-react';
import type { AnalysisResult } from '@/lib/api';
import { PlaceOverlay } from '@/components/PlaceOverlay';

/* The annotated MP4 is served from the backend. A load error shows a way to open the file directly. */
function VideoPlayerInline({ src }: { src: string }) {
  const [error, setError] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);

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

      <video ref={videoRef} src={src} controls autoPlay loop muted playsInline
        className="w-full h-full object-contain" style={{ display: error ? 'none' : 'block' }}
        onLoadedData={() => setLoaded(true)} onError={() => setError(true)} />
    </div>
  );
}

/* The processed video of a finished job, on the result page and when a job is opened from the Jobs list.
   Mall places jobs get the shops drawn over it by the page; the link changes whenever new marks rewrite the file. */
export function AnnotatedVideo({ result }: { result: AnalysisResult }) {
  const src = result.annotated_video_url;
  if (!src) return null;
  const stats = result.stats;
  const places = result.mode === 'places' && result.places_result;

  return (
    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}
      className="glow-border bg-cv-card rounded-2xl overflow-hidden">
      <div className="px-5 py-3 border-b border-cv-border flex items-center gap-2">
        <Film size={15} className="text-cv-accent" />
        <span className="font-semibold text-cv-text text-sm">Annotated Output Video</span>
        <span className="text-cv-sub text-xs font-mono ml-auto">
          {places ? 'Shops · Door lines · Tracked people · Events' : 'Boxes · Track IDs · Live attention time'}
        </span>
      </div>

      {places
        ? <PlaceOverlay src={src} places={places.places} />
        : <VideoPlayerInline src={src} />}

      <div className="px-5 py-3 flex items-center justify-between border-t border-cv-border">
        <span className="text-cv-sub text-xs font-mono">
          {result.mode === 'places'
            ? `${stats?.analysis_fps?.toFixed(1)} FPS (analysed frames) · ${stats?.resolution}`
            : `${stats?.source_fps?.toFixed(1)} FPS · ${stats?.resolution} · ${stats?.total_frames} frames`}
        </span>
        <a href={src} target="_blank" rel="noopener noreferrer"
          className="flex items-center gap-1.5 text-cv-accent hover:text-cv-accentL text-xs font-mono transition-colors">
          <Download size={12} /> Open / Download MP4
        </a>
      </div>
    </motion.div>
  );
}
