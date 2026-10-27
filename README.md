<div align="center">
<img src="https://img.shields.io/badge/YOLOv8n-Detection-6C63FF?style=for-the-badge&logo=python&logoColor=white" />
<img src="https://img.shields.io/badge/ByteTrack-Tracking-06B6D4?style=for-the-badge&logo=python&logoColor=white" />
<img src="https://img.shields.io/badge/FastAPI-Backend-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
<img src="https://img.shields.io/badge/Next.js_14-Frontend-000000?style=for-the-badge&logo=nextdotjs&logoColor=white" />
<img src="https://img.shields.io/badge/Vercel-Deployed-black?style=for-the-badge&logo=vercel&logoColor=white" />
<img src="https://img.shields.io/badge/Railway-Backend-0B0D0E?style=for-the-badge&logo=railway&logoColor=white" />

<br/><br/>

# 👁️ CrowdVision

### Real-Time People Counting & Queue Management System

## 🎥 Demo Video

![demo](https://github.com/user-attachments/assets/4f4272eb-12e1-4131-93d3-3a1bf3a3942f)


> Upload any CCTV video → Get AI-powered people counting, queue analytics,
> dwell time estimation, density heatmap, and smart email alerts — all in your browser.

<br/>
<!--
[![Live Demo](https://img.shields.io/badge/🚀_Live_Demo-Visit_Now-6C63FF?style=for-the-badge)](https://crowdvision.vercel.app)
[![Colab](https://img.shields.io/badge/Open_in-Colab-F9AB00?style=for-the-badge&logo=googlecolab&logoColor=white)](https://colab.research.google.com)
-->
</div>

---

## 📌 About The Project

CrowdVision is a full-stack computer vision web application that solves a real operational problem — managing crowds and queues in retail stores, event venues, and hospitals is done manually, by observation. A supervisor watches the floor and decides when to open another checkout counter. A security guard notices a gate crush only after it has already formed. A hospital administrator walks the corridor to estimate OPD wait times.

**CrowdVision automates this entirely.**

Upload a CCTV video, and the system:
- Detects every person in every frame using YOLOv8n
- Assigns each person a persistent tracking ID using ByteTrack
- Counts who enters and exits through a virtual counting line
- Monitors how many people are inside defined zone polygons
- Tracks how long each person waits in a queue zone
- Fires email alerts when thresholds are exceeded
- Generates a density heatmap showing high-traffic areas
- Streams a live annotated preview to your browser as it processes

No Python installation needed. No Jupyter notebook. Just a browser.

---

## 🎓 Academic Context

| Field | Details |
|---|---|
| **Institute** | Adani Institute of Digital Technology Management (AIDTM), Ahmedabad |
| **Programme** | PGDM — Artificial Intelligence & Data Science |
| **Course** | Computer Vision Project (Trimester 3) |
| **Mentor** | **Mr. Chintan Patel** |

---

## 👥 Team 9

| # | Name |
|---|---|
| 1 | _Rutvik Prajapati_ |
| 2 | _Prarthi Patel_ |
| 3 | _Siddharth Hakani_ |
| 4 | _Dhruv Patel_ |
| 5 | _Heril Shah_ |

---

## 🏭 Target Industries

| Industry | Reference Company | Use Case |
|---|---|---|
| 🏪 **Retail** | DMart · Shoppers Stop | Checkout queue alerts, shelf heatmap, footfall analytics |
| 🎪 **Events** | BookMyShow | Gate surge detection, multi-camera crowd density |
| 🏥 **Healthcare** | Eka Care | OPD waiting time estimation, queue threshold alerts |

---

## ✨ Features

### 🔬 Computer Vision Pipeline

| Feature | How It Works |
|---|---|
| **Person Detection** | YOLOv8n, COCO pretrained, `classes=[0]` — person only. No false positives from bags or trolleys. |
| **Persistent Tracking** | ByteTrack with Kalman filter. Each person gets a stable ID across frames, through occlusion. |
| **IN/OUT Counting** | Virtual line at configurable position. Sign-change detection per track ID — one count per crossing. |
| **Zone Occupancy** | Polygon zones drawn in normalised coords. `cv2.pointPolygonTest` tests each centroid every frame. |
| **Dwell / Wait Time** | Stopwatch per track ID when inside a queue zone. Running average updated live in HUD. |
| **Smart Alert Engine** | Visual banner + Gmail email + sound beep. Sustained timer (Instant to 120s) to prevent alert fatigue. |
| **Density Heatmap** | Float32 accumulator incremented at each centroid. Gaussian smoothed (σ=40). JET colormap output. |
| **ONNX Export** | `model.export(format='onnx', opset=12, simplify=True)`. ~1.3× faster than PyTorch on CPU. |
| **Multi-Camera** | Two feeds processed in same loop. `np.hstack` stitches frames. Combined IN/OUT totals aggregated. |

### 🌐 Web Application

| Feature | Details |
|---|---|
| **Live Frame Preview** | Backend encodes annotated frames as base64 JPEG, pushes via SSE every N frames. User watches pipeline work in real time. |
| **Annotated Video Inline** | HTTP Range responses from FastAPI. `<video controls>` plays output MP4 in browser — no download needed to view. |
| **Drag-and-Drop Upload** | MP4 · AVI · MOV · MKV up to 500 MB. File validation and metadata display before starting. |
| **Settings Panel** | Confidence threshold, zone thresholds, counting line position — all adjustable per video. |
| **Email Alert Config** | Gmail address + App Password + recipient + delay timer UI. "Send Test Email" to verify before analysis. |
| **Analytics Charts** | Recharts time-series: occupancy, IN/OUT flow, FPS — 3 tabs, loaded from `frame_stats.csv`. |
| **One-click ZIP** | All outputs bundled and downloadable immediately after processing completes. |

### 🧪 Failure Case Testing

The system was tested on five synthetic scenarios generated with OpenCV:

| Scenario | Simulation |
|---|---|
| Normal (baseline) | Good lighting, 1–4 persons/sec |
| Night / Low Light | `cv2.convertScaleAbs(alpha=0.28)` + Gaussian noise + green IR tint |
| Camera Shake | Random `warpAffine` ±6px horizontal, ±4px vertical, ±1° rotation per frame |
| Dense Crowd | 10 persons/sec spawn, 15–20 simultaneous with heavy occlusion |
| Queue Buildup | Controlled spawn that crosses threshold at ~18s to test sustained alert timer |

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────┐     SSE + REST     ┌───────────────────────────────┐
│              FRONTEND                    │ ◀────────────────▶ │            BACKEND             │
│           Vercel (Next.js 14)            │                    │       Railway (FastAPI)        │
│                                          │                    │                               │
│  /               Landing page            │  POST /api/analyze │  Receives video + config      │
│  /dashboard      Upload + analysis       │  ──────────────▶  │  Starts background job        │
│                                          │                    │                               │
│  Components:                             │  GET /api/stream/  │  Processes frame by frame     │
│  ├─ StatsPanel.tsx    Live metrics       │  ◀──────────────  │  Pushes progress via SSE      │
│  ├─ AlertBanner.tsx   Alert log          │                    │                               │
│  ├─ AlertSettings.tsx Email config       │  GET /api/download │  Serves outputs with Range    │
│  └─ LiveChart.tsx     Recharts           │  ◀──────────────  │  HTTP for browser video       │
│                                          │                    │                               │
│  lib/api.ts           SSE + fetch        │  POST /api/test-   │  Gmail SMTP verification      │
└──────────────────────────────────────────┘  email             └───────────────────────────────┘
```

### Pipeline — 11 Stages Per Frame

```
┌─────────┐   ┌──────────────┐   ┌────────────────┐   ┌──────────────────┐
│  Video  │──▶│  YOLOv8n     │──▶│  ByteTrack     │──▶│  Centroid        │
│  Read   │   │  Detection   │   │  Tracking      │   │  Extraction      │
└─────────┘   └──────────────┘   └────────────────┘   └──────────────────┘
                                                                │
           ┌────────────────────────────────────────────────────┘
           ▼
┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│  Line Crossing   │──▶│  Zone Occupancy  │──▶│  Dwell Time      │
│  IN / OUT Count  │   │  pointPolygonTest│   │  Per-ID Timer    │
└──────────────────┘   └──────────────────┘   └──────────────────┘
                                                       │
           ┌───────────────────────────────────────────┘
           ▼
┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│  Alert Engine    │──▶│  HUD Render      │──▶│  VideoWriter +   │
│  Email + Sound   │   │  Zones + Boxes   │   │  SSE Push        │
└──────────────────┘   └──────────────────┘   └──────────────────┘
```

---

## 🛠️ Tech Stack

### Backend
| Technology | Version | Purpose |
|---|---|---|
| Python | 3.13 | Core language |
| YOLOv8n (Ultralytics) | ≥ 8.3.0 | Person detection, COCO pretrained |
| ByteTrack | built-in | Multi-object tracking with Kalman filter |
| OpenCV | 4.10 | Frame I/O, drawing, video writing, transforms |
| NumPy | 1.26+ | Centroid math, heatmap accumulation |
| pandas | 2.2 | CSV logging (4 files, flushed every 3s) |
| scipy.ndimage | 1.13 | Gaussian filter for heatmap smoothing |
| matplotlib | 3.9 | 6-panel analytics dashboard PNG |
| FastAPI | 0.111 | Async REST API + SSE streaming |
| uvicorn | 0.30 | ASGI production server |
| smtplib | stdlib | Gmail SMTP email alerts via SSL port 465 |
| ONNX Runtime | opset 12 | Optimised inference, edge deployment |

### Frontend
| Technology | Version | Purpose |
|---|---|---|
| TypeScript | 5 | Type-safe code |
| Next.js | 14.2 | React framework, App Router, Vercel deploy |
| React | 18.3 | Component tree, state management |
| Tailwind CSS | 3.4 | Utility-first styling |
| Framer Motion | 11.3 | Page transitions, live counter animations |
| Recharts | 2.12 | Time-series analytics charts |
| Lucide React | 0.414 | Icon set |
| DM Serif Display | Google Fonts | Display font — headings |
| DM Sans | Google Fonts | Body font — clean readable |
| DM Mono | Google Fonts | Monospaced — data labels |

### Deployment
| Layer | Platform | Tier |
|---|---|---|
| Frontend | Vercel | Free |
| Backend | Railway.app | Free (500 hrs/month) |
| Alternative backend | Render.com | Free (750 hrs/month) |

---

## 📊 Evaluation Metrics

> **No custom training.** YOLOv8n uses pretrained COCO weights. These metrics evaluate inference accuracy on test videos.

| Metric | Category | Expected Range | Meaning |
|---|---|---|---|
| **MAE** | Counting | 1.2 – 2.5 persons | Avg absolute error per frame |
| **RMSE** | Counting | 1.8 – 3.5 | Penalises large misses more |
| **MAPE** | Counting | 8% – 18% | Error as % of true count |
| **R²** | Counting | 0.88 – 0.96 | Tracks real count trend (1.0 = perfect) |
| **Precision** | Detection (IoU ≥ 0.5) | 0.82 – 0.92 | Of all detections, fraction that are real |
| **Recall** | Detection (IoU ≥ 0.5) | 0.78 – 0.88 | Of all real persons, fraction detected |
| **F1 Score** | Detection (IoU ≥ 0.5) | 0.80 – 0.90 | Balanced precision-recall score |

---

## 📁 Project Structure

```
crowdvision/
│
├── 📓 Team9_FINAL_COLAB.ipynb          17-cell standalone Colab pipeline
│
├── 🌐 frontend/                         Next.js app → deploy to Vercel
│   ├── app/
│   │   ├── layout.tsx                   Root layout, Google Fonts, metadata
│   │   ├── globals.css                  Tailwind base + custom animations
│   │   ├── page.tsx                     Landing page (hero, real video demo, features)
│   │   └── dashboard/
│   │       └── page.tsx                 Upload + live preview + results display
│   ├── components/
│   │   ├── StatsPanel.tsx               Live stat cards with zone progress bars
│   │   ├── AlertBanner.tsx              Colour-coded alert log (INFO/WARNING/CRITICAL)
│   │   ├── AlertSettings.tsx            Email config + sustained timer selector UI
│   │   └── LiveChart.tsx                Recharts analytics (3 tabs)
│   ├── lib/
│   │   └── api.ts                       uploadVideo(), streamJobUpdates() SSE client
│   ├── public/
│   │   ├── demo-retail.mp4              ← Place annotated output video here
│   │   ├── demo-event.mp4
│   │   └── demo-corridor.mp4
│   ├── next.config.js                   MIME type fix for .mp4, reactStrictMode off
│   ├── tailwind.config.js
│   ├── tsconfig.json
│   └── package.json
│
├── ⚙️ backend/                          FastAPI Python → deploy to Railway
│   ├── main.py                          Routes: /api/analyze, /api/stream, /api/download
│   ├── processor.py                     Full YOLOv8 + ByteTrack pipeline + AlertEngine
│   ├── requirements.txt
│   ├── Procfile                         Railway startup: uvicorn main:app ...
│   └── railway.toml
│
└── 📖 README.md
```

---

## 🚀 Installation

### Prerequisites
- Python 3.10 or higher
- Node.js 18 or higher
- Git

### Step 1 — Clone

```bash
git clone https://github.com/YOUR_USERNAME/crowdvision.git
cd crowdvision
```

### Step 2 — Backend (Terminal 1)

```bash
cd backend

# Create and activate virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Mac / Linux

# Install all dependencies
pip install fastapi uvicorn[standard] python-multipart ultralytics \
            opencv-python-headless numpy pandas matplotlib scipy Pillow aiofiles

# Configure environment
copy .env.example .env         # Windows
# cp .env.example .env          # Mac / Linux

# Edit .env: set BACKEND_URL=http://localhost:8000

# Run
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

✅ Verify: `http://localhost:8000/health` → `{"status":"ok"}`

> First run downloads YOLOv8n weights (~6 MB) automatically.

### Step 3 — Frontend (Terminal 2)

```bash
cd frontend

npm install

copy .env.example .env.local   # Windows
# cp .env.example .env.local    # Mac / Linux

# Edit .env.local:
# NEXT_PUBLIC_BACKEND_URL=http://localhost:8000

npm run dev
```

✅ Open: `http://localhost:3000`

### Step 4 — Add your demo video

Copy your annotated output video from the Colab pipeline to:

```
frontend/public/demo-retail.mp4
```

The landing page demo section will play it automatically.

---

## 🌐 Deployment

### Frontend → Vercel

```bash
cd frontend
npm install -g vercel
vercel
```

Then in Vercel dashboard → **Settings → Environment Variables** → add:
```
NEXT_PUBLIC_BACKEND_URL = https://your-backend.railway.app
```
Redeploy after adding the variable.

### Backend → Railway.app

1. Push code to GitHub
2. Go to [railway.app](https://railway.app) → **New Project → Deploy from GitHub Repo**
3. Select your repo → set **Root Directory** to `backend`
4. Railway auto-detects `requirements.txt` and uses `Procfile` for startup
5. In **Variables** tab, add:
   ```
   BACKEND_URL = https://your-app-name.railway.app
   OUTPUT_DIR  = /tmp/crowdvision_output
   ```

---

## 📧 Email Alert Setup

1. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
2. Generate an **App Password** (16 characters — not your regular Gmail password)
3. On the dashboard page, click **"Alerts"** button in the top nav
4. Fill in:
   - Your Gmail address
   - The 16-character App Password
   - Recipient email (can be same as yours)
5. Choose alert delay: **Instant** · 10s · 15s · 20s · 30s · 45s · 60s
6. Click **"Send Test Email"** to verify before running analysis

Email fires when:
- Queue zone exceeds threshold for the chosen duration
- General floor overcrowded for the chosen duration
- Entry rate spikes above 2.5 persons/sec

---

## 📤 Output Files

| File | Contents |
|---|---|
| `annotated.mp4` | Input video with bounding boxes, track IDs, polygon zones, HUD, alert banners |
| `heatmap.png` | JET colormap density heatmap — red = high traffic, blue = low traffic |
| `analytics_dashboard.png` | 6-panel matplotlib: occupancy, IN/OUT, entry rate, zones, alerts, hourly footfall |
| `frame_stats.csv` | Per-frame: timestamp, FPS, total_in, total_out, occupancy, zone counts |
| `events.csv` | Every IN/OUT crossing: track_id, event type, zone, centroid x/y |
| `dwell_times.csv` | Per queue visit: track_id, zone, dwell_sec |
| `alerts.csv` | Alert log: timestamp, zone, type (OVERCROWDING/QUEUE_OVERFLOW/RAPID_INFLUX), level, value |
| `results.zip` | All of the above bundled for one-click download |

---

## 💰 Cost Analysis

| Scenario | One-Time Cost | Annual Cost |
|---|---|---|
| Student POC (this project) | ₹ 0 | ₹ 0 |
| Single store — 2 cameras (Raspberry Pi) | ₹ 31,370 | ₹ 7,646 |
| Enterprise — 10 stores, 40 cameras (Jetson Nano) | ₹ 5,83,000 | ₹ 68,000 |
| **Commercial alternative** (RetailNext / ShopperTrak) | ₹ 0 | **₹ 7,20,000 – 19,20,000** |

> Open-source deployment pays back vs commercial subscription in **under 1 month**.

---

## ⚠️ Limitations

| Limitation | Root Cause | Mitigation |
|---|---|---|
| Night detection degrades ~20% | YOLOv8n trained on daylight COCO images | Use IR CCTV camera for dark environments |
| Dense occlusion causes ID switches | Bodies overlapping >60% confuse NMS | Mount camera overhead (60–90°) |
| No cross-camera Re-ID | ByteTrack IDs are per-stream only | Add OSNet embeddings via deep-sort-realtime |
| CPU processing: 4–8 FPS | No GPU acceleration on Raspberry Pi | Use ONNX export (+1.3×) or Jetson Nano (20–25 FPS) |
| Single worker | One video at a time | Add Celery + Redis for concurrent processing |
| Railway free tier sleeps | Container spins down after ~10 min idle | Upgrade to Railway Hobby ($5/mo) |
| Files lost on restart | Railway ephemeral storage | Download ZIP immediately after processing |
| Email: 500/day Gmail limit | Gmail SMTP free tier | Use SendGrid or AWS SES for production |

---

## 🔭 Future Scope

- [ ] **Cross-camera Re-ID** — same person tracked across multiple feeds (OSNet + DeepSORT)
- [ ] **WhatsApp alerts** — Twilio WhatsApp Business API
- [ ] **Streamlit live monitoring dashboard** — real-time ops display
- [ ] **InfluxDB + Grafana** — time-series storage for multi-day trends
- [ ] **Social distancing detection** — pairwise centroid distance alerts
- [ ] **Weighted dwell heatmap** — accumulate by time-in-zone
- [ ] **Cloud-edge hybrid** — edge counts → MQTT → AWS IoT Core
- [ ] **TensorRT INT8 quantisation** — Jetson Nano production performance

---

## 🙏 Acknowledgements

- [**Ultralytics**](https://ultralytics.com) — YOLOv8 and ByteTrack integration
- [**OpenCV**](https://opencv.org) — Computer vision foundation
- [**FastAPI**](https://fastapi.tiangolo.com) — Backend framework
- [**Vercel**](https://vercel.com) — Frontend hosting
- [**Railway**](https://railway.app) — Backend hosting

---

## 📄 License

Academic project — PGDM AI&DS, AIDTM Ahmedabad.
For educational and non-commercial use only.

---

<div align="center">

**👁️ CrowdVision — Team 9**

PGDM Artificial Intelligence & Data Science · Adani Institute of Digital Technology Management

*Mentor: Mr. Chintan Patel*

<br/>

⭐ Star this repo if it helped you!

</div>
