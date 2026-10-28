

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
