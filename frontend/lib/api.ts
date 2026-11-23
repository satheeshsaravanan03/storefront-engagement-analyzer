// lib/api.ts
// Handles all communication with the FastAPI Python backend

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

export type Behaviour = 'glanced' | 'looked' | 'engaged' | 'strong';

export interface Viewer {
  person_id: number;
  first_sec: number;
  last_sec: number;
  present_sec: number;       // time near the camera
  attention_sec: number;     // time near the camera AND facing it
  longest_look_sec: number;
  looks: number;             // separate looks (gaps longer than the tolerance start a new one)
  visits?: number;           // separate appearances; more than 1 = left and came back
  track_ids?: number[];      // tracker IDs matched to this person
  speed: number;             // box-heights per second; low = standing still
  behaviour: Behaviour;      // classified with the thresholds used at processing time
  image?: string;            // snapshot path (engaged / strong viewers only), relative to the job folder
}

/* ── Mall places: shops marked on the floor of one frame ──── */
// 'stand' = attention at one display, 'places' = movement in and out of several shops
export type AnalysisMode = 'stand' | 'places';

export type Point = [number, number];   // x, y as a fraction of the frame (0 to 1)

export interface Place {
  name: string;
  door: [Point, Point];   // two points on the floor at the doorway
  inside: Point;          // a point on the inside of the door line: it tells which way is in
  front: Point[];         // floor area in front of the shop; empty when not marked
}

export type PlaceEventKind = 'enter' | 'exit' | 'peek' | 'stop';

export interface PlaceEvent {
  person_id: number;
  track_id: number | null;
  event: PlaceEventKind;
  place: string;
  time_s: number;
  frame: number;
  duration_s: number | null;   // for 'stop': how long they stood still
  confidence: number;          // 0 to 1; lower when the feet were estimated or the video ended first
  feet_estimated: boolean;
  reason: string;              // enter: stay | vanish | end_of_video; peek: back out
}

export interface PlaceRow {
  name: string;
  entered: number;             // unique people who went in
  entries: number;             // times people went in
  reentries: number;
  exits: number;
  peeks: number;               // stepped in and straight back out (not counted as entered)
  avg_inside_s: number | null; // only where both the enter and the exit were seen
  has_front: boolean;
  stopped: number | null;      // null when no front area was marked
  passed: number | null;
  entered_ids: number[];
  stopped_ids: number[];
}

export interface Overlap {
  people: number;
  combinations: { places: string[]; count: number; person_ids: number[] }[];
  a_not_b: Record<string, Record<string, number>>;   // a_not_b[A][B] = in A but not in B
}

export interface VisitorLink {
  a: number;                   // the two pieces of tracks this join (or doubt) is about
  b: number;
  kind: 'gap' | 'door' | 'swap';   // picked up where they were heading, came back out of the same shop door, or were swapped by the tracker with someone they walked past
  level: 'confirmed' | 'candidate';
  gap_s: number;               // how long they were out of sight between the two
  appearance: number | null;   // how alike the shirt and trousers colours are, 0 to 1 (null when a swap was judged by movement alone)
  motion: number | null;       // distance from where they were heading, as a share of what is allowed (gap links)
  margin: number;              // how much better this pairing is than the next best one
}

/* One person followed through the whole video, whatever the tracker did meanwhile. */
export interface Visitor {
  id: number;
  label: string;               // V001
  tracks: number[];            // the tracker ids this person was seen under
  first_s: number;
  last_s: number;
  seen_s: number;              // time actually seen, without the gaps
  shirt: string | null;        // colours as #rrggbb, from the picture
  trousers: string | null;
  samples: number;
  joined: number;              // pieces of tracks joined into this visitor by confirmed links
  uncertain: boolean;          // a join is only a candidate: this may be the same person as another visitor
  links: VisitorLink[];
}

export interface PlacesResult {
  places: Place[];
  events: PlaceEvent[];
  visitors?: Visitor[];        // absent on jobs from before visitor ids; then people are only numbered #1, #2...
  metrics: {
    places: PlaceRow[];
    overlap_entered: Overlap;
    overlap_interested: Overlap;   // entered or stopped in front
    transitions: Record<string, Record<string, number>>;
    journeys: { places: string[]; count: number; person_ids: number[] }[];
  };
  height_model: { slope: number; offset: number } | null;
}

export interface AnalysisResult {
  job_id: string;
  filename?: string;         // name of the uploaded video
  mode?: AnalysisMode;       // absent on jobs saved before mall places existed: those are 'stand'
  status: 'queued' | 'processing' | 'done' | 'error';
  phase?: string;            // what the backend is doing, e.g. 'tracking people'
  progress: number;          // 0–100
  total_frames: number;
  processed_frames: number;
  fps: number;
  // Final results (available when status === 'done')
  stats?: {
    duration_sec: number;
    resolution: string;
    source_fps: number;
    total_frames: number;
    glance_sec?: number;
    engage_sec?: number;
    strong_sec?: number;
    min_look_sec?: number;
    ignored?: number;        // people near the camera who never looked long enough
    captured?: number;       // snapshots saved
    tracks?: number;         // tracker IDs seen near the camera
    people?: number;         // distinct people after matching returning ones
    analysis_fps?: number;   // places mode: analysed frames per second; the annotated video plays at this rate
    entered?: number;        // places mode: people who went into at least one shop
    stay_sec?: number;       // places mode: seconds inside that count as entered
    stop_sec?: number;       // places mode: seconds standing in front that count as stopped
    memory_sec?: number;     // places mode: how long a lost person is waited for before a new id is final
    estimated_feet?: number; // places mode: share of positions whose feet were worked out from the head
  };
  viewers?: Viewer[];
  viewers_url?: string;       // CSV download URL
  engaged_json_url?: string;  // engaged.json (engaged + strong viewers with snapshot paths)
  places_result?: PlacesResult;
  events_url?: string;        // place_events.csv
  can_adjust?: boolean;       // places mode: false for a job saved before the marks could be adjusted
  annotated_video_url?: string;
  // Live frame (base64 JPEG) during processing
  preview_frame?: string;
  frame_data?: {
    time_sec: number;
    fps: number;
    looking_now?: number;
    viewers?: number;
    engaged?: number;
    strong?: number;
    people_now?: number;     // places mode: people in view
    tracks?: number;         // places mode: tracker IDs seen so far (before returning people are matched)
  };
  error?: string;
}

/* ── Upload and start analysis ────────────────────────────── */
// Fixed detection settings (no longer user-adjustable)
const DETECTION_CONFIDENCE = 0.40;   // minimum confidence for a person detection
const NEARNESS_RATIO = 0.30;         // people shorter than this share of the frame (far away) are ignored

export async function uploadVideo(
  file: File,
  config: {
    glance_sec?: number;
    engage_sec?: number;
    strong_sec?: number;
    min_look_sec?: number;
    mode?: AnalysisMode;
    places?: Place[];      // mall places: the marked shops
    stay_sec?: number;     // mall places: seconds inside that count as entered
    stop_sec?: number;     // mall places: seconds standing in front that count as stopped
  }
): Promise<{ job_id: string }> {
  const form = new FormData();
  form.append('video', file);
  // Mall places uses the backend's own detection settings (people are small in a mall camera)
  form.append('config', JSON.stringify(config.mode === 'places' ? {
    mode:     'places',
    places:   config.places,
    stay_sec: config.stay_sec ?? 2.5,
    stop_sec: config.stop_sec ?? 3,
  } : {
    confidence:   DETECTION_CONFIDENCE,
    near_ratio:   NEARNESS_RATIO,
    glance_sec:   config.glance_sec   ?? 2,
    engage_sec:   config.engage_sec   ?? 5,
    strong_sec:   config.strong_sec   ?? 10,
    min_look_sec: config.min_look_sec ?? 1,
  }));

  const res = await fetch(`${BACKEND}/api/analyze`, {
    method: 'POST',
    body: form,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Upload failed' }));
    throw new Error(err.detail || 'Upload failed');
  }
  return res.json();
}

/* ── Adjust the marks of a finished mall places job ───────── */
// The tracked people are saved with the job, so this analyses them again with the new marks (nobody is detected twice)
export async function recomputePlaces(
  jobId: string,
  places: Place[],
  settings: { stay_sec?: number; stop_sec?: number } = {},
): Promise<AnalysisResult> {
  const res = await fetch(`${BACKEND}/api/jobs/${jobId}/recompute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ places, ...settings }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '' }));
    throw new Error(typeof err.detail === 'string' && err.detail ? err.detail : 'Could not apply the new marks');
  }
  return res.json();
}

/* ── Poll job status ──────────────────────────────────────── */
export async function getJobStatus(jobId: string): Promise<AnalysisResult> {
  const res = await fetch(`${BACKEND}/api/status/${jobId}`);
  if (!res.ok) throw new Error('Failed to fetch job status');
  return res.json();
}

/* ── Stream via SSE (real-time updates) ───────────────────── */
export function streamJobUpdates(
  jobId: string,
  onUpdate: (data: AnalysisResult) => void,
  onDone: (data: AnalysisResult) => void,
  onError: (err: string) => void
): () => void {
  const url = `${BACKEND}/api/stream/${jobId}`;
  const es = new EventSource(url);

  es.onmessage = (event) => {
    try {
      const data: AnalysisResult = JSON.parse(event.data);
      if (data.status === 'done') {
        onDone(data);
        es.close();
      } else if (data.status === 'error') {
        onError(data.error || 'Processing failed');
        es.close();
      } else {
        onUpdate(data);
      }
    } catch {
      // Ignore parse errors
    }
  };

  es.onerror = () => {
    onError('Connection to processing server lost');
    es.close();
  };

  // Return cleanup function
  return () => es.close();
}

/* ── Job records (jobs page) ──────────────────────────────── */
export interface JobSummary {
  job_id: string;
  filename: string;
  mode?: AnalysisMode;
  entered?: number | null;   // places mode: people who went into a shop
  created_at: number;        // unix seconds
  status: AnalysisResult['status'];
  progress: number;
  file_mb: number;
  duration_sec: number | null;
  viewers: number;
  engaged: number;
  strong: number;
  error?: string | null;
}

export async function listJobs(): Promise<JobSummary[]> {
  const res = await fetch(`${BACKEND}/api/jobs`, { cache: 'no-store' });
  if (!res.ok) throw new Error('Failed to load jobs');
  return res.json();
}

export async function deleteJob(jobId: string): Promise<void> {
  const res = await fetch(`${BACKEND}/api/jobs/${jobId}`, { method: 'DELETE' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Delete failed' }));
    throw new Error(err.detail || 'Delete failed');
  }
}

/* ── SerpAPI snapshot lookup (Google Lens) ────────────────── */
/* Public details of a matched page: account/channel, caption, publish date. */
export interface MatchMeta {
  platform: string;
  title?: string | null;
  author?: string | null;
  author_url?: string | null;
  description?: string | null;
  published?: string | null;
  source?: 'oembed' | 'opengraph' | null;
  found: boolean;
  error?: string;
}

export interface LensMatch {
  title?: string;
  source?: string;
  link?: string;
  thumbnail?: string;
  is_video?: boolean;
  meta?: MatchMeta;
}

export interface LensResult {
  image_url: string;
  search_url?: string;
  description?: string | null;   // Google's AI overview of the image; absent in results saved by older versions
  visual_matches: LensMatch[];
}

export async function runLookup(jobId: string, personId: number): Promise<LensResult> {
  const res = await fetch(`${BACKEND}/api/jobs/${jobId}/lookup/${personId}`, { method: 'POST' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Lookup failed' }));
    throw new Error(err.detail || 'Lookup failed');
  }
  return res.json();
}

export async function getMatchMeta(jobId: string, personId: number, index: number): Promise<MatchMeta> {
  const res = await fetch(`${BACKEND}/api/jobs/${jobId}/lookup/${personId}/meta/${index}`, { method: 'POST' });
  if (!res.ok) throw new Error('Could not load details');
  return res.json();
}

export async function getLookup(jobId: string, personId: number): Promise<LensResult | null> {
  const res = await fetch(`${BACKEND}/api/jobs/${jobId}/lookup/${personId}`, { cache: 'no-store' });
  return res.ok ? ((await res.json()) as LensResult | null) : null;
}

/* ── Face matching against the registered people ─────────── */
export interface RegisteredProfile {
  id: string;
  name: string;
  email?: string | null;
  phone?: string | null;
  role?: string | null;
  company?: string | null;
  photo?: string | null;
  registered_at?: string | null;   // ISO time the lead was registered
  photo_status: 'ok' | 'no_photo' | 'missing' | 'no_face';
  face_px: number;
}

export type IdentityStatus = 'matched' | 'possible' | 'unmatched' | 'no_face';

export interface IdentityPerson {
  person_id: number;
  image: string;                       // snapshot path relative to the job folder
  status: IdentityStatus;
  score: number | null;                // cosine similarity of the best candidate
  profile_id: string | null;           // set for matched / possible
  face_px: number;
  candidates: { profile_id: string; score: number }[];
}

export interface IdentityResult {
  registry_size: number;
  with_photo: number;
  thresholds: { match: number; possible: number; margin: number };
  people: IdentityPerson[];
}

export async function listRegistry(): Promise<RegisteredProfile[]> {
  const res = await fetch(`${BACKEND}/api/registry`, { cache: 'no-store' });
  if (!res.ok) throw new Error('Failed to load the registry');
  return res.json();
}

export async function registerLead(form: FormData): Promise<RegisteredProfile> {
  const res = await fetch(`${BACKEND}/api/registry`, { method: 'POST', body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Could not register the lead' }));
    throw new Error(err.detail || 'Could not register the lead');
  }
  return res.json();
}

export async function getIdentities(jobId: string): Promise<IdentityResult | null> {
  const res = await fetch(`${BACKEND}/api/jobs/${jobId}/identify`, { cache: 'no-store' });
  return res.ok ? ((await res.json()) as IdentityResult | null) : null;
}

export async function runIdentify(jobId: string): Promise<IdentityResult> {
  const res = await fetch(`${BACKEND}/api/jobs/${jobId}/identify`, { method: 'POST' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Matching failed' }));
    throw new Error(err.detail || 'Matching failed');
  }
  return res.json();
}

export const registryPhotoUrl = (id: string) => `${BACKEND}/api/registry/photo/${id}`;
export const jobFileUrl = (jobId: string, path: string) => `${BACKEND}/api/file/${jobId}/${path}`;

/* ── Health check ─────────────────────────────────────────── */
export async function checkBackendHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${BACKEND}/health`, { signal: AbortSignal.timeout(5000) });
    return res.ok;
  } catch {
    return false;
  }
}

/* ── Download helpers ─────────────────────────────────────── */
export function getDownloadUrl(jobId: string, file: 'video' | 'original' | 'csv' | 'zip'): string {
  return `${BACKEND}/api/download/${jobId}/${file}`;
}