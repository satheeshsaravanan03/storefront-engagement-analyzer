'use client';

import { useEffect, useState } from 'react';
import { Loader2, SlidersHorizontal, X } from 'lucide-react';
import { getDownloadUrl, recomputePlaces, type AnalysisResult, type Place } from '@/lib/api';
import { PlaceMarker, draftsReady, toDrafts, toPlaces, type PlaceDraft } from '@/components/PlaceMarker';

/* Move the marks of a finished job and get the new result without analysing the video again. */
export function PlaceAdjust({ jobId, places, onDone }: { jobId: string; places: Place[]; onDone: (updated: AnalysisResult) => void }) {
  const [open, setOpen] = useState(false);
  const [drafts, setDrafts] = useState<PlaceDraft[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || busy) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented || (e.target as HTMLElement).tagName === 'INPUT') return;
      e.preventDefault();   // taken: the panel behind this window must not close too
      setOpen(false);
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [open, busy]);

  const start = () => { setDrafts(toDrafts(places)); setError(null); setOpen(true); };

  const apply = async () => {
    setBusy(true); setError(null);
    try {
      const updated = await recomputePlaces(jobId, toPlaces(drafts));
      setOpen(false);
      onDone(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not apply the new marks');
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button onClick={start}
        className="flex items-center gap-2 bg-cv-accent hover:bg-cv-accentL text-white text-xs font-semibold px-3.5 py-2 rounded-xl transition-colors">
        <SlidersHorizontal size={13} /> Adjust marks
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/50" onClick={() => !busy && setOpen(false)} />
          <div className="relative bg-cv-surface border border-cv-border rounded-2xl w-full max-w-4xl max-h-[92vh] overflow-y-auto">
            <div className="px-5 py-4 flex items-center gap-3 border-b border-cv-border">
              <div>
                <h2 className="font-display text-2xl text-cv-text">Adjust the marks</h2>
                <p className="text-cv-sub text-xs mt-0.5">The people are not detected again: the saved tracks are analysed with the new marks.</p>
              </div>
              <button onClick={() => setOpen(false)} disabled={busy} aria-label="Close"
                className="ml-auto text-cv-sub hover:text-cv-text disabled:opacity-40"><X size={18} /></button>
            </div>
            <div className="p-4">
              <PlaceMarker source={getDownloadUrl(jobId, 'original')} drafts={drafts} onChange={setDrafts} />
            </div>
            <div className="px-5 py-4 flex items-center justify-end gap-3 border-t border-cv-border">
              {error && <p className="mr-auto text-sm text-cv-red">{error}</p>}
              <button onClick={() => setOpen(false)} disabled={busy}
                className="px-4 py-2.5 rounded-xl text-sm font-medium text-cv-sub hover:text-cv-text disabled:opacity-40">Cancel</button>
              <button onClick={apply} disabled={busy || !draftsReady(drafts)}
                className="bg-cv-accent hover:bg-cv-accentL disabled:opacity-50 disabled:cursor-not-allowed text-white px-4 py-2.5 rounded-xl text-sm font-semibold flex items-center gap-2 transition-colors">
                {busy && <Loader2 size={14} className="animate-spin" />} Apply and recompute
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
