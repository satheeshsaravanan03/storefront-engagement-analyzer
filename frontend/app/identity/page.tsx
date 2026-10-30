'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Loader2, RefreshCw, Mail, Phone, Briefcase, UserX, UserRoundSearch, ScanFace, ImageOff } from 'lucide-react';
import clsx from 'clsx';
import {
  listJobs, listRegistry, getIdentities, runIdentify, registryPhotoUrl, jobFileUrl,
  type JobSummary, type RegisteredProfile, type IdentityPerson, type IdentityResult, type IdentityStatus,
} from '@/lib/api';
import { AppShell } from '@/components/AppShell';

type Tab = 'matches' | 'registry';

const STATUS: Record<IdentityStatus, { label: string; cls: string; dot: string }> = {
  matched:   { label: 'Matched',        cls: 'bg-cv-green/10 text-cv-green', dot: 'bg-cv-green' },
  possible:  { label: 'Possible match', cls: 'bg-cv-amber/10 text-cv-amber', dot: 'bg-cv-amber' },
  unmatched: { label: 'Unmatched',      cls: 'bg-cv-red/10 text-cv-red',     dot: 'bg-cv-red' },
  no_face:   { label: 'No clear face',  cls: 'bg-cv-sub/10 text-cv-sub',     dot: 'bg-cv-sub' },
};

function StatusBadge({ status }: { status: IdentityStatus }) {
  const s = STATUS[status];
  return <span className={clsx('inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full', s.cls)}>
    <span className={clsx('w-1.5 h-1.5 rounded-full', s.dot)} /> {s.label}
  </span>;
}

function initials(name: string) {
  return name.split(/\s+/).map(w => w[0]).slice(0, 2).join('').toUpperCase();
}

/* A registered person's photo, or their initials when the photo is missing or has no usable face */
function Avatar({ profile, className }: { profile: RegisteredProfile; className?: string }) {
  const [failed, setFailed] = useState(false);
  return profile.photo_status !== 'missing' && profile.photo_status !== 'no_photo' && !failed ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={registryPhotoUrl(profile.id)} alt={profile.name} onError={() => setFailed(true)}
      className={clsx('object-cover bg-cv-black', className)} />
  ) : (
    <div className={clsx('bg-cv-accent/10 text-cv-accent font-display flex items-center justify-center', className)}>
      {initials(profile.name)}
    </div>
  );
}

function Contact({ profile }: { profile: RegisteredProfile }) {
  const row = 'flex items-center gap-2.5 text-sm text-cv-text min-w-0';
  return (
    <div className="space-y-2">
      {profile.role && <p className={row}><Briefcase size={14} className="text-cv-sub shrink-0" />
        <span className="truncate">{profile.role}{profile.company ? ` · ${profile.company}` : ''}</span></p>}
      {profile.email && <p className={row}><Mail size={14} className="text-cv-sub shrink-0" />
        <a href={`mailto:${profile.email}`} className="truncate hover:text-cv-accent">{profile.email}</a></p>}
      {profile.phone && <p className={row}><Phone size={14} className="text-cv-sub shrink-0" />
        <a href={`tel:${profile.phone.replace(/\s/g, '')}`} className="truncate hover:text-cv-accent">{profile.phone}</a></p>}
    </div>
  );
}

/* ID card for one viewer: the captured snapshot on the left, the registered person on the right */
function IdCard({ jobId, person, byId }: { jobId: string; person: IdentityPerson; byId: Map<string, RegisteredProfile> }) {
  const profile = person.profile_id ? byId.get(person.profile_id) : undefined;
  const others = person.candidates.filter(c => c.profile_id !== person.profile_id);
  const closest = person.status === 'unmatched' && person.candidates[0] ? byId.get(person.candidates[0].profile_id) : undefined;

  return (
    <div className="glow-border bg-cv-card rounded-2xl overflow-hidden">
      <div className="px-5 py-3 border-b border-cv-border flex items-center gap-3">
        <span className="font-semibold text-cv-text text-sm">Viewer #{person.person_id}</span>
        <StatusBadge status={person.status} />
        {person.score != null && person.status !== 'no_face' && (
          <span className="ml-auto text-cv-sub text-xs font-mono">similarity {(Math.max(0, person.score) * 100).toFixed(0)}%</span>
        )}
      </div>

      <div className="p-5 grid gap-5 sm:grid-cols-[180px_1fr]">
        <div>
          <p className="text-[11px] font-semibold tracking-wider text-cv-sub mb-2">CAPTURED</p>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={jobFileUrl(jobId, person.image)} alt={`Viewer ${person.person_id}`}
            className="w-full max-h-72 object-cover rounded-xl border border-cv-border bg-cv-black" />
        </div>

        <div className="min-w-0">
          {profile ? (
            <>
              <p className="text-[11px] font-semibold tracking-wider text-cv-sub mb-2">
                {person.status === 'matched' ? 'REGISTERED PROFILE' : 'CLOSEST REGISTERED PROFILE · PLEASE CONFIRM'}
              </p>
              <div className="flex items-start gap-4 mb-4">
                <Avatar profile={profile} className="w-20 h-20 rounded-xl border border-cv-border text-2xl shrink-0" />
                <div className="min-w-0">
                  <p className="font-display text-2xl text-cv-text leading-tight truncate">{profile.name}</p>
                  <p className="text-cv-sub text-xs font-mono mt-1">{profile.id}</p>
                </div>
              </div>
              <Contact profile={profile} />
            </>
          ) : (
            <div className="h-full min-h-[140px] flex flex-col items-center justify-center text-center gap-2 rounded-xl border border-dashed border-cv-border p-5">
              {person.status === 'no_face'
                ? <ImageOff size={26} className="text-cv-sub" />
                : <UserX size={26} className="text-cv-red" />}
              <p className="font-semibold text-cv-text">
                {person.status === 'no_face' ? 'No clear face in this snapshot' : 'Unmatched: not in the registered list'}
              </p>
              <p className="text-cv-sub text-xs max-w-xs">
                {person.status === 'no_face'
                  ? 'The face is too small, turned away or blurred to compare.'
                  : 'No registered person looks like this viewer closely enough to name them.'}
                {closest && ` Closest was ${closest.name} (${(Math.max(0, person.score ?? 0) * 100).toFixed(0)}%), below the match threshold.`}
              </p>
            </div>
          )}

          {others.length > 0 && profile && (
            <div className="mt-4 pt-4 border-t border-cv-border">
              <p className="text-[11px] font-semibold tracking-wider text-cv-sub mb-2">OTHER CANDIDATES</p>
              <div className="flex flex-wrap gap-2">
                {others.map(c => (
                  <span key={c.profile_id} className="text-xs text-cv-sub bg-cv-black rounded-lg px-2.5 py-1">
                    {byId.get(c.profile_id)?.name ?? c.profile_id} · {(Math.max(0, c.score) * 100).toFixed(0)}%
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function RegistryCard({ profile }: { profile: RegisteredProfile }) {
  const warn = {
    ok: null,
    no_photo: 'No photo set',
    missing: `Photo not found: add registry/photos/${profile.photo ?? profile.id + '.jpg'}`,
    no_face: 'No face found in the photo',
  }[profile.photo_status];
  return (
    <div className="glow-border bg-cv-card rounded-2xl p-4">
      <div className="flex items-center gap-3 mb-3">
        <Avatar profile={profile} className="w-14 h-14 rounded-xl border border-cv-border text-lg shrink-0" />
        <div className="min-w-0">
          <p className="font-semibold text-cv-text truncate">{profile.name}</p>
          <p className="text-cv-sub text-xs font-mono">{profile.id}</p>
        </div>
      </div>
      <Contact profile={profile} />
      {warn && <p className="mt-3 text-xs text-cv-amber bg-cv-amber/10 rounded-lg px-2.5 py-1.5">{warn}</p>}
    </div>
  );
}

export default function IdentityPage() {
  const [tab, setTab] = useState<Tab>('matches');
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [jobId, setJobId] = useState<string>('');
  const [registry, setRegistry] = useState<RegisteredProfile[]>([]);
  const [result, setResult] = useState<IdentityResult | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const byId = useMemo(() => new Map(registry.map(p => [p.id, p])), [registry]);

  // Finished videos that have at least one captured viewer
  useEffect(() => {
    Promise.all([listJobs(), listRegistry()])
      .then(([j, r]) => {
        const usable = j.filter(x => x.status === 'done' && (x.engaged + x.strong) > 0)
          .sort((a, b) => b.created_at - a.created_at);
        setJobs(usable); setRegistry(r);
        const wanted = new URLSearchParams(window.location.search).get('job');   // /identity?job=<id>
        const first = usable.find(x => x.job_id === wanted) ?? usable[0];
        if (first) setJobId(first.job_id);
      })
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load'));
  }, []);

  const load = useCallback(async (id: string) => {
    if (!id) return;
    setLoading(true); setError(null);
    try {
      let r = await getIdentities(id);
      if (!r) r = await runIdentify(id);   // finished before matching existed: run it now
      setResult(r);
      setSelected(r.people[0]?.person_id ?? null);
    } catch (e) {
      setResult(null); setError(e instanceof Error ? e.message : 'Failed to load matches');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(jobId); }, [jobId, load]);

  const rerun = async () => {
    if (!jobId) return;
    setRunning(true); setError(null);
    try {
      const [r, reg] = await Promise.all([runIdentify(jobId), listRegistry()]);
      setResult(r); setRegistry(reg);
      setSelected(prev => (r.people.some(p => p.person_id === prev) ? prev : r.people[0]?.person_id ?? null));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Matching failed');
    } finally { setRunning(false); }
  };

  const person = result?.people.find(p => p.person_id === selected);
  const counts = useMemo(() => {
    const c = { matched: 0, possible: 0, unmatched: 0, no_face: 0 };
    result?.people.forEach(p => { c[p.status] += 1; });
    return c;
  }, [result]);

  const TABS: { id: Tab; label: string; count?: number }[] = [
    { id: 'matches',  label: 'Matches',    count: result?.people.length },
    { id: 'registry', label: 'Registered', count: registry.length },
  ];

  return (
    <AppShell>
      <div>
        <div className="mb-6 flex items-end justify-between gap-4 flex-wrap">
          <div>
            <p className="text-xs font-semibold tracking-wider text-cv-accent mb-2">IDENTITY</p>
            <h1 className="font-display text-4xl text-cv-text mb-2">Who was watching</h1>
            <p className="text-cv-sub">Each engaged viewer's face is compared with the registered people. Clothes are ignored.</p>
          </div>
          <div className="flex items-center gap-3 flex-wrap">
            <select value={jobId} onChange={e => setJobId(e.target.value)} aria-label="Video"
              className="glow-border bg-cv-card text-cv-text text-sm rounded-xl px-3 py-2.5 max-w-[260px]">
              {jobs.length === 0 && <option value="">No finished videos</option>}
              {jobs.map(j => (
                <option key={j.job_id} value={j.job_id}>
                  {j.filename} · {new Date(j.created_at * 1000).toLocaleDateString()}
                </option>
              ))}
            </select>
            <button onClick={rerun} disabled={!jobId || running}
              className="bg-cv-accent hover:bg-cv-accentL disabled:opacity-50 text-white px-4 py-2.5 rounded-xl text-sm font-semibold flex items-center gap-2 transition-colors">
              {running ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} Re-run matching
            </button>
          </div>
        </div>

        {/* Main sub-navigation */}
        <div className="flex gap-1 border-b border-cv-border mb-6">
          {TABS.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={clsx('px-4 py-2.5 text-sm font-medium -mb-px border-b-2 transition-colors',
                tab === t.id ? 'border-cv-accent text-cv-accent' : 'border-transparent text-cv-sub hover:text-cv-text')}>
              {t.label}{t.count != null && <span className="ml-2 text-xs bg-cv-black rounded-full px-2 py-0.5">{t.count}</span>}
            </button>
          ))}
        </div>

        {error && <p className="mb-4 text-sm text-cv-red bg-cv-red/10 rounded-xl px-4 py-3">{error}</p>}

        {tab === 'registry' && (
          registry.length === 0
            ? <p className="text-cv-sub">The registry is empty. Add people to backend/registry/profiles.json.</p>
            : <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{registry.map(p => <RegistryCard key={p.id} profile={p} />)}</div>
        )}

        {tab === 'matches' && (
          loading ? (
            <div className="flex items-center gap-2 text-cv-sub py-10"><Loader2 size={16} className="animate-spin" /> Matching faces…</div>
          ) : !result ? (
            <div className="text-center py-16 text-cv-sub">
              <UserRoundSearch size={30} className="mx-auto mb-3" />
              {jobs.length === 0 ? 'Analyse a video with engaged viewers first.' : 'Pick a video to see its matches.'}
            </div>
          ) : (
            <>
              {result.with_photo === 0 && (
                <p className="mb-4 text-sm text-cv-amber bg-cv-amber/10 rounded-xl px-4 py-3">
                  None of the {result.registry_size} registered people has a usable photo yet, so nobody can be matched.
                  Add photos to backend/registry/photos/ and press Re-run matching.
                </p>
              )}
              <div className="flex flex-wrap gap-x-5 gap-y-1 mb-4 text-sm text-cv-sub">
                {(Object.keys(counts) as IdentityStatus[]).map(k => (
                  <span key={k} className="flex items-center gap-1.5">
                    <span className={clsx('w-2 h-2 rounded-full', STATUS[k].dot)} /> {counts[k]} {STATUS[k].label.toLowerCase()}
                  </span>
                ))}
              </div>

              {/* One small tab per viewer */}
              <div role="tablist" className="flex gap-2 overflow-x-auto pb-2 mb-5">
                {result.people.map(p => {
                  const prof = p.profile_id ? byId.get(p.profile_id) : undefined;
                  const active = p.person_id === selected;
                  return (
                    <button key={p.person_id} role="tab" aria-selected={active} onClick={() => setSelected(p.person_id)}
                      className={clsx('shrink-0 flex items-center gap-2.5 pl-1.5 pr-3.5 py-1.5 rounded-full border text-sm transition-colors',
                        active ? 'border-cv-accent bg-cv-accent/10 text-cv-accent' : 'border-cv-border bg-cv-card text-cv-text hover:border-cv-accent/40')}>
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={jobFileUrl(jobId, p.image)} alt="" className="w-8 h-8 rounded-full object-cover object-top bg-cv-black" />
                      <span className="font-medium">{prof && p.status === 'matched' ? prof.name.split(' ')[0] : `#${p.person_id}`}</span>
                      <span className={clsx('w-2 h-2 rounded-full', STATUS[p.status].dot)} />
                    </button>
                  );
                })}
              </div>

              {person
                ? <IdCard jobId={jobId} person={person} byId={byId} />
                : <p className="text-cv-sub flex items-center gap-2"><ScanFace size={16} /> No captured viewers in this video.</p>}
            </>
          )
        )}
      </div>
    </AppShell>
  );
}
