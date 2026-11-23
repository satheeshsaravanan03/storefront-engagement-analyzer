'use client';

import { useState } from 'react';
import { Download, FileText, Layers, Route, SlidersHorizontal, Store, Users } from 'lucide-react';
import clsx from 'clsx';
import { PlaceAdjust } from '@/components/PlaceAdjust';
import type { AnalysisResult, Overlap, PlaceEventKind, PlaceRow, PlacesResult, Visitor, VisitorLink } from '@/lib/api';

const EVENT_LABEL: Record<PlaceEventKind, string> = {
  enter: 'Entered',
  exit:  'Exited',
  peek:  'Peeked in',
  stop:  'Stopped in front',
};
const EVENT_BADGE: Record<PlaceEventKind, string> = {
  enter: 'bg-cv-green/15 text-cv-green',
  exit:  'bg-cv-amber/15 text-cv-amber',
  peek:  'bg-cv-border text-cv-sub',
  stop:  'bg-cv-cyan/15 text-cv-cyan',
};
const REASON: Record<string, string> = {
  stay:         'stayed inside',
  vanish:       'went out of view',
  end_of_video: 'video ended first',
  'back out':   'came straight back out',
};

/* A person is V001 when the video was analysed with visitor ids, and #1 on jobs from before them. */
const nameOf = (result: PlacesResult) => {
  const known = new Map((result.visitors ?? []).map(v => [v.id, v]));
  return (id: number) => known.get(id)?.label ?? `#${id}`;
};
const ids = (result: PlacesResult, v: number[]) => v.map(nameOf(result)).join(' ');

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

/* One card per shop. */
export function ShopCards({ rows }: { rows: PlaceRow[] }) {
  return (
    <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {rows.map(r => {
        const lines: [string, string | number][] = [
          ['Entries', r.reentries ? `${r.entries} (${r.reentries} came back)` : r.entries],
          ['Exits seen', r.exits],
          ['Peeked in, not counted', r.peeks],
          ['Stopped in front', r.stopped ?? 'no front area'],
          ['Passed by', r.passed ?? 'no front area'],
          ['Average time inside', r.avg_inside_s != null ? `${r.avg_inside_s}s` : 'not seen'],
        ];
        return (
          <div key={r.name} className="glow-border bg-cv-card rounded-2xl p-4">
            <div className="flex items-center gap-2 mb-3">
              <Store size={15} className="text-cv-accent flex-shrink-0" />
              <span className="font-semibold text-cv-text truncate" title={r.name}>{r.name}</span>
            </div>
            <p className="font-display text-4xl text-cv-text">{r.entered}</p>
            <p className="text-cv-sub text-xs font-mono mt-1 mb-3">people entered</p>
            <dl className="space-y-1.5">
              {lines.map(([k, v]) => (
                <div key={k} className="flex items-center justify-between gap-3 text-xs">
                  <dt className="text-cv-sub">{k}</dt>
                  <dd className="font-mono text-cv-text text-right">{v}</dd>
                </div>
              ))}
            </dl>
          </div>
        );
      })}
    </div>
  );
}

function SummaryText({ result, stats }: { result: PlacesResult; stats?: AnalysisResult['stats'] }) {
  const rows = result.metrics.places;
  const entered = result.metrics.overlap_entered.people;
  const dur = stats?.duration_sec ?? 0;
  const guessed = Math.round((stats?.estimated_feet ?? 0) * 100);
  return (
    <div className="glow-border bg-cv-card rounded-2xl p-5">
      <p className="text-cv-sub text-xs font-mono mb-2">SUMMARY</p>
      <p className="text-cv-text text-sm leading-relaxed">
        {entered === 0
          ? `No one was seen going into ${rows.length === 1 ? 'the shop' : 'any of the shops'} in ${dur.toFixed(0)}s of footage.`
          : `${entered} ${entered === 1 ? 'person' : 'people'} went into ${rows.filter(r => r.entered).length} of ${rows.length} ` +
            `${rows.length === 1 ? 'shop' : 'shops'} in ${dur.toFixed(0)}s of footage: ` +
            rows.map(r => `${r.name} ${r.entered}`).join(', ') + '.'}
      </p>
      <p className="text-cv-sub text-xs mt-3 leading-relaxed">
        Only the feet are checked against the marked door lines. Someone counts as having entered when their feet cross the line inward
        and they stay inside for {stats?.stay_sec ?? 2.5}s or go out of view; stepping in and straight back out is shown as a peek and is not counted.
        {result.visitors?.length
          ? `A person the tracker loses and finds again, or swaps with someone they walked past, is followed from shirt and trousers colour,
             where they were heading and how long they were out of sight, and given one visitor number (V001) for the whole video. A match is
             only used when it is clear; when two answers are close the person is kept apart and marked uncertain, so people dressed alike are
             not merged but one person may be counted twice.`
          : 'A person who is lost and picked up again is matched to the same ID from clothing colour, so people dressed alike may occasionally be merged or one person split.'}
        {guessed > 0 && ` About ${guessed}% of positions had hidden feet, which were worked out from the head; events that rely on them show a lower confidence.`}
      </p>
    </div>
  );
}

const swatch = (hex: string | null, what: string) => (
  <span title={hex ? `${what} ${hex}` : `${what} not seen`} className="w-5 h-5 rounded-md border border-cv-border flex-shrink-0"
    style={{ background: hex ?? 'transparent' }} />
);

const linkText = (l: VisitorLink) => {
  const colours = l.appearance != null ? `colours ${Math.round(l.appearance * 100)}% alike` : 'judged by how they moved';
  if (l.kind === 'swap') return `Put back: the tracker swapped them with someone they walked past (${colours})`;
  const how = l.kind === 'door' ? `came back out of the same door after ${mmss(l.gap_s)}` : `out of sight ${l.gap_s.toFixed(1)}s`;
  const where = l.kind === 'gap' && l.motion != null ? `, ${l.motion <= 1 ? 'where they were heading' : 'a little off course'}` : '';
  return `${l.level === 'confirmed' ? 'Joined' : 'Possibly the same'}: ${colours}, ${how}${where}`;
};

function VisitorCard({ v }: { v: Visitor }) {
  return (
    <div className="bg-cv-surface border border-cv-border rounded-xl p-3">
      <div className="flex items-center gap-2">
        <span className="font-mono font-bold text-cv-text text-sm">{v.label}</span>
        {v.uncertain && (
          <span title="This may be the same person as another visitor: the evidence was not clear enough to join them"
            className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-cv-amber/15 text-cv-amber">uncertain</span>
        )}
        <span className="ml-auto flex gap-1.5">{swatch(v.shirt, 'Shirt')}{swatch(v.trousers, 'Trousers')}</span>
      </div>
      <p className="text-cv-sub text-[11px] font-mono mt-1.5">
        {mmss(v.first_s)}–{mmss(v.last_s)} · seen {v.seen_s.toFixed(0)}s
        {v.joined > 0 && ` · ${v.joined + 1} tracks joined`}
      </p>
      {v.links.length > 0 && (
        <details className="mt-1.5">
          <summary className="text-cv-sub text-[11px] cursor-pointer hover:text-cv-text">Why</summary>
          <ul className="mt-1 space-y-0.5">
            {v.links.map(l => (
              <li key={`${l.a}-${l.b}`} className={clsx('text-[11px] leading-snug', l.level === 'confirmed' ? 'text-cv-sub' : 'text-cv-amber')}>
                {linkText(l)}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/* The people the video was followed through, with the colours they were recognised by. */
function VisitorsCard({ visitors }: { visitors: Visitor[] }) {
  const doubtful = visitors.filter(v => v.uncertain).length;
  return (
    <div className="glow-border bg-cv-card rounded-2xl overflow-hidden">
      <div className="px-5 py-3 border-b border-cv-border flex items-center gap-2 flex-wrap">
        <Users size={15} className="text-cv-accent" />
        <span className="font-semibold text-cv-text text-sm">Visitors</span>
        <span className="text-cv-sub text-xs font-mono ml-auto">
          {visitors.length} {visitors.length === 1 ? 'person' : 'people'}{doubtful > 0 && ` · ${doubtful} uncertain`}
        </span>
      </div>
      <div className="p-4 grid sm:grid-cols-2 lg:grid-cols-3 gap-3 max-h-96 overflow-y-auto">
        {visitors.map(v => <VisitorCard key={v.id} v={v} />)}
      </div>
    </div>
  );
}

function OverlapCard({ result }: { result: PlacesResult }) {
  const [basis, setBasis] = useState<'entered' | 'interested'>('entered');
  const names = result.metrics.places.map(p => p.name);
  const ov: Overlap = basis === 'entered' ? result.metrics.overlap_entered : result.metrics.overlap_interested;
  const pill = (b: typeof basis, text: string) => (
    <button key={b} onClick={() => setBasis(b)}
      className={clsx('px-3.5 py-1.5 rounded-full text-xs font-medium border transition-colors',
        basis === b ? 'bg-cv-accent text-white border-cv-accent' : 'bg-cv-card text-cv-text border-cv-border hover:border-cv-accent/40')}>
      {text}
    </button>
  );
  return (
    <div className="glow-border bg-cv-card rounded-2xl overflow-hidden">
      <div className="px-5 py-3 border-b border-cv-border flex items-center gap-2 flex-wrap">
        <Layers size={15} className="text-cv-accent" />
        <span className="font-semibold text-cv-text text-sm">Who visited which shops</span>
        <div className="ml-auto flex gap-2">
          {pill('entered', 'Entered')}
          {pill('interested', 'Entered or stopped in front')}
        </div>
      </div>
      <table className="w-full text-sm">
        <thead className="bg-cv-card text-cv-sub text-xs font-mono">
          <tr className="border-b border-cv-border">
            <th className="text-left px-5 py-2 font-normal">Shops</th>
            <th className="text-right px-3 py-2 font-normal">People</th>
            <th className="text-left px-5 py-2 font-normal">Who</th>
          </tr>
        </thead>
        <tbody>
          {ov.combinations.map(c => (
            <tr key={c.places.join('|')} className="border-b border-cv-border/50 text-cv-text">
              <td className="px-5 py-2">{c.places.length === 1 ? `Only ${c.places[0]}` : c.places.join(' + ')}</td>
              <td className="px-3 py-2 text-right font-mono font-bold">{c.count}</td>
              <td className="px-5 py-2 font-mono text-xs text-cv-sub">{ids(result, c.person_ids)}</td>
            </tr>
          ))}
          {ov.combinations.length === 0 && (
            <tr><td colSpan={3} className="px-5 py-6 text-center text-cv-sub text-xs font-mono">Nobody yet</td></tr>
          )}
        </tbody>
      </table>

      {names.length > 1 && (
        <div className="px-5 py-4 border-t border-cv-border overflow-x-auto">
          <p className="text-cv-sub text-xs font-mono mb-2">IN THE ROW SHOP BUT NOT IN THE COLUMN SHOP</p>
          <table className="text-sm">
            <thead>
              <tr>
                <th className="pr-4" />
                {names.map(n => <th key={n} className="px-3 py-1 text-cv-sub text-xs font-mono font-normal text-right">{n}</th>)}
              </tr>
            </thead>
            <tbody>
              {names.map(a => (
                <tr key={a}>
                  <td className="pr-4 py-1 text-cv-text">{a}</td>
                  {names.map(b => (
                    <td key={b} className="px-3 py-1 text-right font-mono text-cv-text">{a === b ? '—' : ov.a_not_b[a]?.[b] ?? 0}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function JourneysCard({ result }: { result: PlacesResult }) {
  const names = result.metrics.places.map(p => p.name);
  const { journeys, transitions } = result.metrics;
  return (
    <div className="glow-border bg-cv-card rounded-2xl overflow-hidden">
      <div className="px-5 py-3 border-b border-cv-border flex items-center gap-2">
        <Route size={15} className="text-cv-cyan" />
        <span className="font-semibold text-cv-text text-sm">Order of visits</span>
        <span className="text-cv-sub text-xs font-mono ml-auto">shops people went into, in order</span>
      </div>
      <table className="w-full text-sm">
        <thead className="text-cv-sub text-xs font-mono">
          <tr className="border-b border-cv-border">
            <th className="text-left px-5 py-2 font-normal">Journey</th>
            <th className="text-right px-3 py-2 font-normal">People</th>
            <th className="text-left px-5 py-2 font-normal">Who</th>
          </tr>
        </thead>
        <tbody>
          {journeys.map(j => (
            <tr key={j.places.join('>')} className="border-b border-cv-border/50 text-cv-text">
              <td className="px-5 py-2">{j.places.join(' → ')}</td>
              <td className="px-3 py-2 text-right font-mono font-bold">{j.count}</td>
              <td className="px-5 py-2 font-mono text-xs text-cv-sub">{ids(result, j.person_ids)}</td>
            </tr>
          ))}
          {journeys.length === 0 && (
            <tr><td colSpan={3} className="px-5 py-6 text-center text-cv-sub text-xs font-mono">Nobody went into a shop</td></tr>
          )}
        </tbody>
      </table>

      {names.length > 1 && (
        <div className="px-5 py-4 border-t border-cv-border overflow-x-auto">
          <p className="text-cv-sub text-xs font-mono mb-2">WENT STRAIGHT FROM THE ROW SHOP TO THE COLUMN SHOP</p>
          <table className="text-sm">
            <thead>
              <tr>
                <th className="pr-4" />
                {names.map(n => <th key={n} className="px-3 py-1 text-cv-sub text-xs font-mono font-normal text-right">{n}</th>)}
              </tr>
            </thead>
            <tbody>
              {names.map(a => (
                <tr key={a}>
                  <td className="pr-4 py-1 text-cv-text">{a}</td>
                  {names.map(b => (
                    <td key={b} className="px-3 py-1 text-right font-mono text-cv-text">{a === b ? '—' : transitions[a]?.[b] ?? 0}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function EventsCard({ result, eventsUrl }: { result: PlacesResult; eventsUrl?: string }) {
  const name = nameOf(result);
  const uncertain = new Set((result.visitors ?? []).filter(v => v.uncertain).map(v => v.id));
  return (
    <div className="glow-border bg-cv-card rounded-2xl overflow-hidden">
      <div className="px-5 py-3 border-b border-cv-border flex items-center gap-2">
        <FileText size={15} className="text-cv-cyan" />
        <span className="font-semibold text-cv-text text-sm">Events</span>
        {eventsUrl && (
          <a href={eventsUrl} download
            className="ml-auto flex items-center gap-1.5 text-cv-accent hover:text-cv-accentL text-xs font-mono transition-colors">
            <Download size={12} /> place_events.csv
          </a>
        )}
      </div>
      <div className="max-h-96 overflow-y-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-cv-card text-cv-sub text-xs font-mono">
            <tr className="border-b border-cv-border">
              <th className="text-right px-5 py-2 font-normal">Time</th>
              <th className="text-left px-3 py-2 font-normal">Person</th>
              <th className="text-left px-3 py-2 font-normal">Event</th>
              <th className="text-left px-3 py-2 font-normal">Shop</th>
              <th className="text-right px-3 py-2 font-normal">Confidence</th>
              <th className="text-left px-5 py-2 font-normal">Note</th>
            </tr>
          </thead>
          <tbody>
            {result.events.map((e, i) => (
              <tr key={i} className="border-b border-cv-border/50 text-cv-text">
                <td className="px-5 py-2 text-right font-mono">{e.time_s.toFixed(1)}s</td>
                <td className="px-3 py-2 font-mono whitespace-nowrap">
                  {name(e.person_id)}
                  {uncertain.has(e.person_id) && (
                    <span title="This may be the same person as another visitor"
                      className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded bg-cv-amber/15 text-cv-amber">uncertain</span>
                  )}
                </td>
                <td className="px-3 py-2">
                  <span className={clsx('text-[11px] font-mono px-2 py-0.5 rounded whitespace-nowrap', EVENT_BADGE[e.event])}>
                    {EVENT_LABEL[e.event]}
                  </span>
                </td>
                <td className="px-3 py-2">{e.place}</td>
                <td className={clsx('px-3 py-2 text-right font-mono', e.confidence < 0.7 && 'text-cv-amber')}>{e.confidence.toFixed(2)}</td>
                <td className="px-5 py-2 text-cv-sub text-xs">
                  {e.event === 'stop' && e.duration_s != null ? `stood still ${e.duration_s}s` : (REASON[e.reason] ?? '')}
                  {e.feet_estimated && ' · feet estimated'}
                </td>
              </tr>
            ))}
            {result.events.length === 0 && (
              <tr><td colSpan={6} className="px-5 py-6 text-center text-cv-sub text-xs font-mono">No events recorded</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* Everything a mall-places job produced. */
export function PlaceResults({ result, stats, eventsUrl, jobId, canAdjust, onChanged }: {
  result: PlacesResult;
  stats?: AnalysisResult['stats'];
  eventsUrl?: string;
  jobId?: string;
  canAdjust?: boolean;       // false for a job saved before the marks could be adjusted
  onChanged?: (updated: AnalysisResult) => void;   // called with the new result after new marks were applied
}) {
  return (
    <div className="space-y-4">
      {jobId && canAdjust && onChanged && (
        <div className="glow-border bg-cv-card rounded-2xl px-5 py-3 flex items-center gap-3 flex-wrap">
          <SlidersHorizontal size={15} className="text-cv-accent flex-shrink-0" />
          <div className="min-w-0">
            <p className="text-cv-text text-sm font-medium">A mark in the wrong place?</p>
            <p className="text-cv-sub text-xs">Move it and get the new result in seconds. The video is not analysed again.</p>
          </div>
          <div className="ml-auto"><PlaceAdjust jobId={jobId} places={result.places} onDone={onChanged} /></div>
        </div>
      )}
      <ShopCards rows={result.metrics.places} />
      <SummaryText result={result} stats={stats} />
      {!!result.visitors?.length && <VisitorsCard visitors={result.visitors} />}
      {result.metrics.places.length > 1 && <OverlapCard result={result} />}
      {result.metrics.places.length > 1 && <JourneysCard result={result} />}
      <EventsCard result={result} eventsUrl={eventsUrl} />
    </div>
  );
}
