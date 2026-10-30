'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Loader2, RefreshCw, Mail, Phone, Briefcase, UserX, ImageOff, ScanFace } from 'lucide-react';
import clsx from 'clsx';
import {
  getIdentities, listRegistry, runIdentify, registryPhotoUrl, jobFileUrl,
  type IdentityPerson, type IdentityResult, type IdentityStatus, type RegisteredProfile,
} from '@/lib/api';

export const STATUS: Record<IdentityStatus, { label: string; cls: string; dot: string }> = {
  matched:   { label: 'Matched',        cls: 'bg-cv-green/10 text-cv-green', dot: 'bg-cv-green' },
  possible:  { label: 'Possible match', cls: 'bg-cv-amber/10 text-cv-amber', dot: 'bg-cv-amber' },
  unmatched: { label: 'Unmatched',      cls: 'bg-cv-red/10 text-cv-red',     dot: 'bg-cv-red' },
  no_face:   { label: 'No clear face',  cls: 'bg-cv-sub/10 text-cv-sub',     dot: 'bg-cv-sub' },
};

const ORDER: Record<IdentityStatus, number> = { matched: 0, possible: 1, unmatched: 2, no_face: 3 };

export function StatusBadge({ status }: { status: IdentityStatus }) {
  const s = STATUS[status];
  return (
    <span className={clsx('inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full', s.cls)}>
      <span className={clsx('w-1.5 h-1.5 rounded-full', s.dot)} /> {s.label}
    </span>
  );
}

const initials = (name: string) => name.split(/\s+/).map(w => w[0]).slice(0, 2).join('').toUpperCase();

/* A registered person's photo, or their initials when there is no photo */
export function Avatar({ profile, className }: { profile: RegisteredProfile; className?: string }) {
  const [failed, setFailed] = useState(false);
  const hasPhoto = profile.photo_status !== 'missing' && profile.photo_status !== 'no_photo' && !failed;
  return hasPhoto ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={registryPhotoUrl(profile.id)} alt={profile.name} onError={() => setFailed(true)}
      className={clsx('object-cover object-top bg-cv-black', className)} />
  ) : (
    <div className={clsx('bg-cv-accent/10 text-cv-accent font-display flex items-center justify-center', className)}>
      {initials(profile.name)}
    </div>
  );
}

export function ContactLines({ profile }: { profile: RegisteredProfile }) {
  const row = 'flex items-center gap-2 text-sm text-cv-text min-w-0';
  return (
    <div className="space-y-1.5">
      {profile.role && (
        <p className={row}><Briefcase size={13} className="text-cv-sub shrink-0" />
          <span className="truncate">{profile.role}{profile.company ? ` · ${profile.company}` : ''}</span></p>
      )}
      {profile.email && (
        <p className={row}><Mail size={13} className="text-cv-sub shrink-0" />
          <a href={`mailto:${profile.email}`} className="truncate hover:text-cv-accent">{profile.email}</a></p>
      )}
      {profile.phone && (
        <p className={row}><Phone size={13} className="text-cv-sub shrink-0" />
          <a href={`tel:${profile.phone.replace(/\s/g, '')}`} className="truncate hover:text-cv-accent">{profile.phone}</a></p>
      )}
    </div>
  );
}

/* One viewer: the captured snapshot next to the registered photo and details */
function LeadCard({ jobId, person, byId }: { jobId: string; person: IdentityPerson; byId: Map<string, RegisteredProfile> }) {
  const profile = person.profile_id ? byId.get(person.profile_id) : undefined;
  const pct = person.score != null ? Math.round(Math.max(0, person.score) * 100) : null;
  const closest = !profile && person.status === 'unmatched' && person.candidates[0]
    ? byId.get(person.candidates[0].profile_id) : undefined;

  return (
    <div className="glow-border bg-cv-card rounded-2xl overflow-hidden flex flex-col">
      <div className="grid grid-cols-2 gap-px bg-cv-border">
        <div className="relative bg-cv-black">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={jobFileUrl(jobId, person.image)} alt={`Viewer ${person.person_id}`}
            className="w-full h-44 object-cover object-top" />
          <span className="absolute left-2 bottom-2 text-[10px] font-semibold tracking-wider bg-black/60 text-white rounded px-1.5 py-0.5">
            CAPTURED · #{person.person_id}
          </span>
        </div>
        <div className="relative bg-cv-black">
          {profile ? (
            <>
              <Avatar profile={profile} className="w-full h-44 text-4xl" />
              <span className="absolute left-2 bottom-2 text-[10px] font-semibold tracking-wider bg-black/60 text-white rounded px-1.5 py-0.5">
                REGISTERED
              </span>
            </>
          ) : (
            <div className="w-full h-44 flex items-center justify-center">
              {person.status === 'no_face' ? <ImageOff size={26} className="text-cv-sub" /> : <UserX size={26} className="text-cv-red" />}
            </div>
          )}
        </div>
      </div>

      <div className="p-4 flex-1 flex flex-col gap-3">
        <div className="flex items-center gap-2 flex-wrap">
          <StatusBadge status={person.status} />
          {pct != null && person.status !== 'no_face' && (
            <span className="ml-auto text-cv-sub text-xs font-mono">similarity {pct}%</span>
          )}
        </div>

        {profile ? (
          <>
            <div className="min-w-0">
              <p className="font-display text-xl text-cv-text leading-tight truncate">{profile.name}</p>
              <p className="text-cv-sub text-xs font-mono">{profile.id}</p>
            </div>
            <ContactLines profile={profile} />
            {person.status === 'possible' && (
              <p className="text-xs text-cv-amber">Please confirm: the score is below the confident-match level.</p>
            )}
          </>
        ) : (
          <div>
            <p className="font-semibold text-cv-text text-sm">
              {person.status === 'no_face' ? 'No clear face in this snapshot' : 'Unmatched: not in the registered list'}
            </p>
            <p className="text-cv-sub text-xs mt-1">
              {person.status === 'no_face'
                ? 'The face is too small, turned away or blurred to compare.'
                : 'No registered lead looks like this viewer closely enough to name them.'}
              {closest && ` Closest was ${closest.name} (${Math.round(Math.max(0, person.score ?? 0) * 100)}%).`}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

/* Recognised visitors of one analysed video, as cards. Matching runs automatically when a video finishes. */
export function MatchedLeads({ jobId }: { jobId: string }) {
  const [result, setResult] = useState<IdentityResult | null>(null);
  const [registry, setRegistry] = useState<RegisteredProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const byId = useMemo(() => new Map(registry.map(p => [p.id, p])), [registry]);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [reg, saved] = await Promise.all([listRegistry(), getIdentities(jobId)]);
      setRegistry(reg);
      setResult(saved ?? await runIdentify(jobId));   // videos finished before matching existed
    } catch (e) {
      setResult(null); setError(e instanceof Error ? e.message : 'Could not load matches');
    } finally { setLoading(false); }
  }, [jobId]);

  useEffect(() => { load(); }, [load]);

  const rerun = async () => {
    setRunning(true); setError(null);
    try {
      const [res, reg] = await Promise.all([runIdentify(jobId), listRegistry()]);
      setResult(res); setRegistry(reg);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Matching failed');
    } finally { setRunning(false); }
  };

  const people = useMemo(
    () => [...(result?.people ?? [])].sort((a, b) => ORDER[a.status] - ORDER[b.status] || a.person_id - b.person_id),
    [result]);
  const matched = people.filter(p => p.status === 'matched').length;

  return (
    <div className="glow-border bg-cv-card rounded-2xl overflow-hidden">
      <div className="px-5 py-3 border-b border-cv-border flex items-center gap-3">
        <ScanFace size={15} className="text-cv-accent shrink-0" />
        <span className="font-semibold text-cv-text text-sm">Recognised leads</span>
        {result && <span className="text-cv-sub text-xs">{matched} of {people.length} viewers matched</span>}
        <button onClick={rerun} disabled={running || loading}
          className="ml-auto flex items-center gap-1.5 text-xs font-medium text-cv-sub hover:text-cv-text disabled:opacity-50 transition-colors">
          {running ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Re-run matching
        </button>
      </div>

      <div className="p-5">
        {loading ? (
          <p className="flex items-center gap-2 text-cv-sub text-sm"><Loader2 size={15} className="animate-spin" /> Matching faces…</p>
        ) : error ? (
          <p className="text-sm text-cv-red">{error}</p>
        ) : people.length === 0 ? (
          <p className="text-cv-sub text-sm">No captured viewers in this video.</p>
        ) : (
          <>
            {result && result.with_photo === 0 && (
              <p className="mb-4 text-sm text-cv-amber bg-cv-amber/10 rounded-xl px-4 py-3">
                None of the registered leads has a photo yet, so nobody can be matched. Add photos on the Leads page.
              </p>
            )}
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {people.map(p => <LeadCard key={p.person_id} jobId={jobId} person={p} byId={byId} />)}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
