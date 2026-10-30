'use client';

import { Fragment, useState } from 'react';
import { Clock, Users, TrendingUp, Zap, FileText, Download, Search, Loader2, ExternalLink, X, Sparkles, Play, ChevronDown, ChevronUp, Film } from 'lucide-react';
import clsx from 'clsx';
import { getDownloadUrl, getLookup, getMatchMeta, runLookup } from '@/lib/api';
import type { Behaviour, LensMatch, LensResult, MatchMeta, Viewer } from '@/lib/api';

export function classify(attention: number, glance: number, engage: number, strong: number): Behaviour {
  if (attention >= strong) return 'strong';
  if (attention >= engage) return 'engaged';
  if (attention >= glance) return 'looked';
  return 'glanced';
}

const LABEL: Record<Behaviour, string> = {
  glanced: 'Glanced',
  looked:  'Stopped & looked',
  engaged: 'Engaged',
  strong:  'Strongly engaged',
};
const BADGE: Record<Behaviour, string> = {
  glanced: 'bg-cv-border text-cv-sub',
  looked:  'bg-cv-cyan/15 text-cv-cyan',
  engaged: 'bg-cv-amber/15 text-cv-amber',
  strong:  'bg-cv-green/15 text-cv-green',
};

export function summarize(viewers: Viewer[], glance: number, engage: number, strong: number) {
  const cls = viewers.map(v => classify(v.attention_sec, glance, engage, strong));
  const count = (b: Behaviour) => cls.filter(c => c === b).length;
  const att = viewers.map(v => v.attention_sec);
  const avg = att.length ? att.reduce((a, b) => a + b, 0) / att.length : 0;
  const max = att.length ? Math.max(...att) : 0;
  return {
    total: viewers.length,
    glanced: count('glanced'), looked: count('looked'),
    engaged: count('engaged'), strong: count('strong'),
    avg, max,
  };
}

type Thresholds = { viewers: Viewer[]; glanceSec: number; engageSec: number; strongSec: number };

/* Counts and summary text. Viewers are re-classified from the raw attention
   times, so changing the thresholds updates instantly. */
export function SummaryCards({ viewers, glanceSec, engageSec, strongSec, durationSec, ignored, compact }: Thresholds & {
  durationSec: number;
  ignored: number;
  compact?: boolean;   // two cards per row, for a narrow column
}) {
  const s = summarize(viewers, glanceSec, engageSec, strongSec);
  const interested = s.engaged + s.strong;

  const cards = [
    { icon: Users,      label: 'Viewers (looked at display)', value: s.total,    color: 'text-cv-accent' },
    { icon: TrendingUp, label: 'Engaged or more',             value: interested, color: 'text-cv-amber'  },
    { icon: Zap,        label: 'Strongly engaged',            value: s.strong,   color: 'text-cv-green'  },
    { icon: Clock,      label: 'Avg / longest attention',     value: `${s.avg.toFixed(1)}s / ${s.max.toFixed(1)}s`, color: 'text-cv-cyan' },
  ];

  return (
    <div className="space-y-4">
      <div className={clsx('grid grid-cols-2 gap-3', !compact && 'lg:grid-cols-4')}>
        {cards.map(({ icon: Icon, label, value, color }) => (
          <div key={label} className="glow-border bg-cv-card rounded-2xl p-4">
            <Icon size={15} className={clsx(color, 'mb-2')} />
            <p className="font-display text-2xl text-cv-text">{value}</p>
            <p className="text-cv-sub text-xs font-mono mt-1">{label}</p>
          </div>
        ))}
      </div>

      <div className="glow-border bg-cv-card rounded-2xl p-5">
        <p className="text-cv-sub text-xs font-mono mb-2">SUMMARY</p>
        <p className="text-cv-text text-sm leading-relaxed">
          {s.total === 0
            ? `No one was seen looking at the display in ${durationSec.toFixed(0)}s of footage.`
            : `${s.total} viewer${s.total === 1 ? '' : 's'} looked at the display over ${durationSec.toFixed(0)}s of footage: ` +
              `${s.glanced} glanced (under ${glanceSec}s), ${s.looked} stopped and looked (${glanceSec}–${engageSec}s), ` +
              `${s.engaged} engaged (${engageSec}–${strongSec}s) and ${s.strong} strongly engaged (${strongSec}s or more). ` +
              `Average attention ${s.avg.toFixed(1)}s, longest ${s.max.toFixed(1)}s.`}
        </p>
        <p className="text-cv-sub text-xs mt-3 leading-relaxed">
          {ignored} other {ignored === 1 ? 'person was' : 'people were'} near the camera but never looked long enough to count.
          People far away or just passing are not counted. Attention is measured from head direction, not eye
          gaze, and does not confirm purchase intent. A person who leaves and comes back is matched to the same ID
          from clothing and hair colour, so people dressed alike may occasionally be merged or one person split.
        </p>
      </div>
    </div>
  );
}

function hostOf(url?: string) {
  try { return url ? new URL(url).hostname.replace(/^www\./, '') : ''; } catch { return ''; }
}

/* Detail panel shown under a viewer row: their snapshot beside a grid of Google Lens matches. */
function LookupPanel({ jobId, personId, image, state, onClose }: {
  jobId: string;
  personId: number;
  image?: string;
  state: { busy: boolean; error: string; result: LensResult | null };
  onClose: () => void;
}) {
  const { busy, error, result } = state;
  const matches: IndexedMatch[] = (result?.visual_matches ?? []).map((m, idx) => ({ ...m, idx }));
  const videos = matches.filter(m => m.is_video);
  const pages = matches.filter(m => !m.is_video);
  return (
    <div className="bg-cv-bg/40 px-5 py-4">
      <div className="flex items-center gap-3 mb-3">
        {image && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={image} alt={`Viewer ${personId}`} className="h-14 w-10 object-cover rounded border border-cv-border" />
        )}
        <div className="min-w-0">
          <p className="text-cv-text text-sm font-semibold">Matches for #{personId}</p>
          <p className="text-cv-sub text-xs font-mono">
            {busy ? 'Searching…' : result ? `${matches.length} visual match${matches.length === 1 ? '' : 'es'}` : ''}
          </p>
        </div>
        <div className="ml-auto flex items-center gap-3">
          {result?.search_url && (
            <a href={result.search_url} target="_blank" rel="noopener noreferrer"
              className="flex items-center gap-1 text-cv-accent hover:text-cv-accentL text-xs font-mono">
              <ExternalLink size={12} /> Google Lens
            </a>
          )}
          <button onClick={onClose} aria-label="Close" className="text-cv-sub hover:text-cv-text"><X size={14} /></button>
        </div>
      </div>

      {busy && <div className="flex items-center gap-2 text-cv-sub text-xs font-mono py-3"><Loader2 size={14} className="animate-spin" /> Searching…</div>}
      {error && <p className="text-red-400 text-xs">{error}</p>}
      {result && matches.length === 0 && <p className="text-cv-sub text-xs">No matches found.</p>}

      {result?.description && (
        <div className="mb-4 rounded-xl border border-cv-border bg-cv-card p-3">
          <p className="text-cv-sub text-[11px] font-mono mb-1 flex items-center gap-1.5"><Sparkles size={12} /> GOOGLE AI DESCRIPTION</p>
          <p className="text-cv-text text-sm leading-relaxed">{result.description}</p>
          <p className="text-cv-sub text-[11px] mt-2">Summarised from the matches below. It describes the scene, may be wrong, and does not identify anyone.</p>
        </div>
      )}

      {videos.length > 0 && (
        <MatchGroup title={`Videos (${videos.length})`} matches={videos} limit={6} jobId={jobId} personId={personId} />
      )}
      {pages.length > 0 && (
        <MatchGroup title={`Other pages (${pages.length})`} matches={pages} limit={6} jobId={jobId} personId={personId} />
      )}
    </div>
  );
}

type IndexedMatch = LensMatch & { idx: number };

/* One match card; "Details" loads the account, caption and date from the page itself. */
function MatchCard({ m, jobId, personId }: { m: IndexedMatch; jobId: string; personId: number }) {
  const [meta, setMeta] = useState<MatchMeta | undefined>(m.meta);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const toggle = async () => {
    setOpen(o => !o);
    if (meta || busy) return;
    setBusy(true);
    try { setMeta(await getMatchMeta(jobId, personId, m.idx)); }
    catch { setMeta({ platform: m.source ?? '', found: false, error: 'Could not load details' }); }
    finally { setBusy(false); }
  };

  return (
    <div className="rounded-xl border border-cv-border bg-cv-card hover:border-cv-accent transition-colors p-2">
      <a href={m.link} target="_blank" rel="noopener noreferrer" className="flex gap-3">
        <div className="relative h-14 w-14 shrink-0">
          {m.thumbnail ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={m.thumbnail} alt="" className="h-14 w-14 rounded-lg object-cover bg-cv-border" />
          ) : <div className="h-14 w-14 rounded-lg bg-cv-border" />}
          {m.is_video && (
            <span className="absolute inset-0 flex items-center justify-center rounded-lg bg-black/35">
              <Play size={16} className="text-white" fill="currentColor" />
            </span>
          )}
        </div>
        <div className="min-w-0">
          <p className="text-cv-text text-xs leading-snug line-clamp-2">{m.title || m.link}</p>
          <p className="text-cv-sub text-[11px] font-mono mt-1 truncate">{m.source || hostOf(m.link)}</p>
        </div>
      </a>
      <button onClick={toggle} className="mt-2 flex items-center gap-1 text-cv-accent hover:text-cv-accentL text-[11px] font-mono">
        {busy ? <Loader2 size={11} className="animate-spin" /> : open ? <ChevronUp size={11} /> : <ChevronDown size={11} />} Details
      </button>
      {open && !busy && meta && (
        <dl className="mt-2 space-y-1.5 text-xs border-t border-cv-border pt-2">
          {!meta.found && <p className="text-cv-sub">{meta.error ?? 'The site shares no public details for this link.'}</p>}
          {(meta.author || meta.platform) && (
            <div>
              <dt className="text-cv-sub text-[11px] font-mono">{meta.platform.toUpperCase()} ACCOUNT / CHANNEL</dt>
              <dd className="text-cv-text">
                {meta.author_url ? (
                  <a href={meta.author_url} target="_blank" rel="noopener noreferrer" className="hover:text-cv-accentL">{meta.author}</a>
                ) : (meta.author ?? '-')}
              </dd>
            </div>
          )}
          {meta.published && (
            <div>
              <dt className="text-cv-sub text-[11px] font-mono">PUBLISHED</dt>
              <dd className="text-cv-text">{new Date(meta.published).toString() === 'Invalid Date' ? meta.published : new Date(meta.published).toLocaleDateString()}</dd>
            </div>
          )}
          {meta.description && (
            <div>
              <dt className="text-cv-sub text-[11px] font-mono">DESCRIPTION</dt>
              <dd className="text-cv-text whitespace-pre-line line-clamp-6">{meta.description}</dd>
            </div>
          )}
        </dl>
      )}
    </div>
  );
}

function MatchGroup({ title, matches, limit, jobId, personId }: {
  title: string; matches: IndexedMatch[]; limit: number; jobId: string; personId: number;
}) {
  const [all, setAll] = useState(false);
  const shown = all ? matches : matches.slice(0, limit);
  return (
    <div className="mb-4">
      <p className="text-cv-sub text-xs font-mono mb-2">{title.toUpperCase()}</p>
      <div className="grid gap-2 items-start grid-cols-[repeat(auto-fill,minmax(220px,1fr))]">
        {shown.map(m => <MatchCard key={m.idx} m={m} jobId={jobId} personId={personId} />)}
      </div>
      {matches.length > limit && (
        <button onClick={() => setAll(a => !a)} className="mt-2 text-cv-accent hover:text-cv-accentL text-xs font-mono">
          {all ? 'Show fewer' : `Show all ${matches.length}`}
        </button>
      )}
    </div>
  );
}

/* Per-viewer table with snapshots and the CSV / JSON links. */
export function ViewersTable({ viewers, glanceSec, engageSec, strongSec, csvUrl, jsonUrl, imageBase, jobId }: Thresholds & {
  csvUrl?: string;
  jsonUrl?: string;    // engaged.json
  imageBase?: string;  // prefix for snapshot paths, e.g. http://host/api/file/<job>/
  jobId?: string;      // enables the SerpAPI "Look up" column
}) {
  const [openId, setOpenId] = useState<number | null>(null);
  const [lookups, setLookups] = useState<Record<number, { busy: boolean; error: string; result: LensResult | null }>>({});

  const toggleLookup = async (personId: number) => {
    if (!jobId) return;
    if (openId === personId) { setOpenId(null); return; }
    setOpenId(personId);
    if (lookups[personId]?.result) return;
    setLookups(l => ({ ...l, [personId]: { busy: true, error: '', result: null } }));
    try {
      // results saved by an older version have no description field, so search again
      const cached = await getLookup(jobId, personId);
      const result = cached && 'description' in cached ? cached : await runLookup(jobId, personId);
      setLookups(l => ({ ...l, [personId]: { busy: false, error: '', result } }));
    } catch (e) {
      setLookups(l => ({ ...l, [personId]: { busy: false, error: e instanceof Error ? e.message : 'Lookup failed', result: null } }));
    }
  };

  return (
      <div className="glow-border bg-cv-card rounded-2xl overflow-hidden">
        <div className="px-5 py-3 border-b border-cv-border flex items-center gap-2">
          <FileText size={15} className="text-cv-cyan" />
          <span className="font-semibold text-cv-text text-sm">Viewers</span>
          <div className="ml-auto flex items-center gap-4">
            {jsonUrl && (
              <a href={jsonUrl} target="_blank" rel="noopener noreferrer"
                className="flex items-center gap-1.5 text-cv-accent hover:text-cv-accentL text-xs font-mono transition-colors">
                <Download size={12} /> engaged.json
              </a>
            )}
            {csvUrl && (
              <a href={csvUrl} download
                className="flex items-center gap-1.5 text-cv-accent hover:text-cv-accentL text-xs font-mono transition-colors">
                <Download size={12} /> viewers.csv
              </a>
            )}
          </div>
        </div>
        <div className="max-h-96 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-cv-card text-cv-sub text-xs font-mono">
              <tr className="border-b border-cv-border">
                <th className="text-left px-5 py-2 font-normal">ID</th>
                <th className="text-left px-3 py-2 font-normal">Snapshot</th>
                <th className="text-right px-3 py-2 font-normal">First seen</th>
                <th className="text-right px-3 py-2 font-normal">Attention</th>
                <th className="text-right px-3 py-2 font-normal">Looks</th>
                <th className="text-left px-5 py-2 font-normal">Behaviour</th>
                {jobId && <th className="text-left px-3 py-2 font-normal">Lookup</th>}
              </tr>
            </thead>
            <tbody>
              {viewers.map(v => {
                const c = classify(v.attention_sec, glanceSec, engageSec, strongSec);
                const open = openId === v.person_id;
                const state = lookups[v.person_id];
                const cols = jobId ? 7 : 6;
                return (
                  <Fragment key={v.person_id}>
                    <tr className={clsx('border-b border-cv-border/50 text-cv-text', open && 'bg-cv-accent/5')}>
                      <td className="px-5 py-2 font-mono">#{v.person_id}</td>
                      <td className="px-3 py-2">
                        {v.image && imageBase ? (
                          <a href={imageBase + v.image} target="_blank" rel="noopener noreferrer">
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img src={imageBase + v.image} alt={`Viewer ${v.person_id}`}
                              className="h-12 w-9 object-cover rounded border border-cv-border" />
                          </a>
                        ) : <span className="text-cv-sub text-xs">-</span>}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">{v.first_sec.toFixed(1)}s</td>
                      <td className="px-3 py-2 text-right font-mono font-bold">{v.attention_sec.toFixed(1)}s</td>
                      <td className="px-3 py-2 text-right font-mono">{v.looks}</td>
                      <td className="px-5 py-2">
                        <span className={clsx('text-[11px] font-mono px-2 py-0.5 rounded whitespace-nowrap', BADGE[c])}>{LABEL[c]}</span>
                      </td>
                      {jobId && (
                        <td className="px-3 py-2">
                          {v.image ? (
                            <button onClick={() => toggleLookup(v.person_id)} disabled={state?.busy}
                              className="flex items-center gap-1.5 text-xs font-mono px-2.5 py-1 rounded-lg border border-cv-border text-cv-accent hover:border-cv-accent disabled:opacity-50 transition-colors">
                              {state?.busy ? <Loader2 size={12} className="animate-spin" /> : <Search size={12} />}
                              {open ? 'Hide' : state?.result ? 'View' : 'Look up'}
                            </button>
                          ) : <span className="text-cv-sub text-xs">-</span>}
                        </td>
                      )}
                    </tr>
                    {open && state && (
                      <tr className="border-b border-cv-border/50">
                        <td colSpan={cols} className="p-0">
                          <LookupPanel jobId={jobId!} personId={v.person_id} image={v.image && imageBase ? imageBase + v.image : undefined}
                            state={state} onClose={() => setOpenId(null)} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
              {viewers.length === 0 && (
                <tr><td colSpan={jobId ? 7 : 6} className="px-5 py-6 text-center text-cv-sub text-xs font-mono">No viewers recorded</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
  );
}

/* The video exactly as it was uploaded, shown under the viewers table. */
export function UploadedVideo({ jobId, filename }: { jobId: string; filename?: string }) {
  const [open, setOpen] = useState(false);   // closed by default; the video only loads once opened
  const [failed, setFailed] = useState(false);
  const src = getDownloadUrl(jobId, 'original');
  return (
    <div className="glow-border bg-cv-card rounded-2xl overflow-hidden">
      <button onClick={() => setOpen(o => !o)} aria-expanded={open}
        className={clsx('w-full px-5 py-3 flex items-center gap-2 text-left', open && 'border-b border-cv-border')}>
        <Film size={15} className="text-cv-accent" />
        <span className="font-semibold text-cv-text text-sm">Uploaded video</span>
        {filename && <span className="text-cv-sub text-xs font-mono ml-auto truncate">{filename}</span>}
        <ChevronDown size={16} className={clsx('text-cv-sub shrink-0 transition-transform', !filename && 'ml-auto', open && 'rotate-180')} />
      </button>
      {open && (failed ? (
        <p className="px-5 py-6 text-cv-sub text-xs">
          This file format can&rsquo;t be played in the browser.{' '}
          <a href={src} className="text-cv-accent hover:text-cv-accentL">Download the original</a>
        </p>
      ) : (
        <video src={src} controls preload="metadata" playsInline onError={() => setFailed(true)}
          className="w-full bg-black" style={{ maxHeight: 420 }} />
      ))}
    </div>
  );
}

/* Both together (used by the jobs side panel). */
export function EngagementResults(p: Thresholds & {
  durationSec: number;
  ignored: number;
  csvUrl?: string;
  jsonUrl?: string;
  imageBase?: string;
  jobId?: string;
  filename?: string;   // shown on the uploaded-video card
}) {
  return (
    <div className="space-y-4">
      <SummaryCards {...p} />
      <ViewersTable {...p} />
      {p.jobId && <UploadedVideo jobId={p.jobId} filename={p.filename} />}
    </div>
  );
}
