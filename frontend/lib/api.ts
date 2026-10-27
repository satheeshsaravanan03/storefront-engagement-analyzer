// lib/api.ts
// Handles all communication with the FastAPI Python backend

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

export interface Zone { x1: number; y1: number; x2: number; y2: number }  // ratios 0–1

export type Category = 'not_flagged' | 'potential' | 'strong';

export interface Visit {
  track_id: number;
  entry_sec: number;
  exit_sec: number;
  dwell_sec: number;
  category: Category;        // classified with the thresholds used at processing time
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
    engage_sec: number;
    strong_sec: number;
  };
  visits?: Visit[];
  visits_url?: string;        // CSV download URL
  annotated_video_url?: string;
  // Live frame (base64 JPEG) during processing
  preview_frame?: string;
  frame_data?: {
    time_sec: number;
    in_zone_now: number;
    visits: number;
    potential: number;
    strong: number;
    fps: number;
  };
  error?: string;
}

/* ── Upload and start analysis ────────────────────────────── */
export async function uploadVideo(
  file: File,
  config: {
    zone: Zone;
    confidence?: number;
    engage_sec?: number;
    strong_sec?: number;
    grace_sec?: number;
  }
): Promise<{ job_id: string }> {
  const form = new FormData();
  form.append('video', file);
  form.append('config', JSON.stringify({
    zone:       config.zone,
    confidence: config.confidence ?? 0.40,
    engage_sec: config.engage_sec ?? 5,
    strong_sec: config.strong_sec ?? 10,
    grace_sec:  config.grace_sec  ?? 1.5,
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