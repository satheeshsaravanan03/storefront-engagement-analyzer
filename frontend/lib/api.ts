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

export interface AnalysisResult {
  job_id: string;
  status: 'queued' | 'processing' | 'done' | 'error';
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
    glance_sec: number;
    engage_sec: number;
    strong_sec: number;
    min_look_sec: number;
    ignored: number;         // people near the camera who never looked long enough
    captured?: number;       // snapshots saved
    tracks?: number;         // tracker IDs seen near the camera
    people?: number;         // distinct people after matching returning ones
  };
  viewers?: Viewer[];
  viewers_url?: string;       // CSV download URL
  engaged_json_url?: string;  // engaged.json (engaged + strong viewers with snapshot paths)
  annotated_video_url?: string;
  // Live frame (base64 JPEG) during processing
  preview_frame?: string;
  frame_data?: {
    time_sec: number;
    looking_now: number;
    viewers: number;
    engaged: number;
    strong: number;
    fps: number;
  };
  error?: string;
}

/* ── Upload and start analysis ────────────────────────────── */
export async function uploadVideo(
  file: File,
  config: {
    confidence?: number;
    glance_sec?: number;
    engage_sec?: number;
    strong_sec?: number;
    min_look_sec?: number;
    near_ratio?: number;
  }
): Promise<{ job_id: string }> {
  const form = new FormData();
  form.append('video', file);
  form.append('config', JSON.stringify({
    confidence:   config.confidence   ?? 0.40,
    glance_sec:   config.glance_sec   ?? 2,
    engage_sec:   config.engage_sec   ?? 5,
    strong_sec:   config.strong_sec   ?? 10,
    min_look_sec: config.min_look_sec ?? 1,
    near_ratio:   config.near_ratio   ?? 0.30,
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
export function getDownloadUrl(jobId: string, file: 'video' | 'csv' | 'zip'): string {
  return `${BACKEND}/api/download/${jobId}/${file}`;
}