// lib/api.ts
// Handles all communication with the FastAPI Python backend

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

export interface AnalysisResult {
  job_id: string;
  status: 'queued' | 'processing' | 'done' | 'error';
  progress: number;          // 0–100
  total_frames: number;
  processed_frames: number;
  fps: number;
  // Final results (available when status === 'done')
  stats?: {
    total_in: number;
    total_out: number;
    peak_occupancy: number;
    avg_dwell_sec: number | null;
    total_alerts: number;
    duration_sec: number;
    resolution: string;
    source_fps: number;
  };
  zones?: Array<{
    name: string;
    type: 'queue' | 'general';
    current_count: number;
    max_count: number;
    alert_threshold: number;
  }>;
  alerts?: Array<{
    timestamp: string;
    zone: string;
    type: string;
    level: string;
    value: number;
    threshold: number;
  }>;
  frame_stats_url?: string;   // CSV download URL
  events_url?: string;
  dwell_url?: string;
  annotated_video_url?: string;
  heatmap_url?: string;
  // Live frame (base64 JPEG) during processing
  preview_frame?: string;
  frame_data?: {
    live_count: number;
    count_in: number;
    count_out: number;
    occupancy: number;
    entry_rate: number;
    avg_dwell: number | null;
    zone_counts: Record<string, number>;
    fps: number;
  };
  error?: string;
}

/* ── Upload and start analysis ────────────────────────────── */
export async function uploadVideo(
  file: File,
  config: {
    confidence?: number;
    overcrowd_thresh?: number;
    queue_thresh?: number;
    sustained_sec?: number;
    line_position?: number;
    // Email alert fields
    email_enabled?: boolean;
    email_from?: string;
    email_password?: string;
    email_to?: string;
  } = {}
): Promise<{ job_id: string }> {
  const form = new FormData();
  form.append('video', file);
  form.append('config', JSON.stringify({
    confidence:       config.confidence       ?? 0.40,
    overcrowd_thresh: config.overcrowd_thresh ?? 10,
    queue_thresh:     config.queue_thresh     ?? 6,
    sustained_sec:    config.sustained_sec    ?? 30,
    line_position:    config.line_position    ?? 0.72,
    // Email config — send these so backend can fire alerts
    email_enabled:  config.email_enabled  ?? false,
    email_from:     config.email_from     ?? '',
    email_password: config.email_password ?? '',
    email_to:       config.email_to       ?? '',
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
export function getDownloadUrl(jobId: string, file: 'video' | 'heatmap' | 'csv' | 'zip'): string {
  return `${BACKEND}/api/download/${jobId}/${file}`;
}