# 🚀 Production Deployment Guide

This guide contains everything you need to deploy the **AI LaTeX Resume Maker** to production.

---

## 🏗 Recommended Architecture: Vercel + Google Cloud Run + GCS

```
                         [ USER BROWSER ]
                                 │
                                 ▼
        ┌───────────────────────────────────────────────────┐
        │       FRONTEND: Vercel (Global Edge CDN)          │
        │       - React / Vite Single Page App              │
        │       - Cost: $0.00 / Month (Free Hobby Tier)     │
        │       - Fast initial page loads (<50ms TTFB)      │
        └─────────────────────────┬─────────────────────────┘
                                  │ API Requests (/api/*)
                                  ▼
        ┌───────────────────────────────────────────────────┐
        │       BACKEND: Google Cloud Run (GCR)             │
        │       - FastAPI + Gunicorn Multi-Worker           │
        │       - Tectonic LaTeX Compilation Engine         │
        │       - SHA-256 PDF Content-Addressable Cache     │
        │       - Auto-scales: 0 instances ➔ 10 instances    │
        │       - Cost: $0.00 when idle                     │
        │         (~$0.84/hr only during 100-user surges)   │
        └─────────────────────────┬─────────────────────────┘
                                  │ Volume Mount (/app/backend/data)
                                  ▼
        ┌───────────────────────────────────────────────────┐
        │       PERSISTENCE: Google Cloud Storage (GCS)     │
        │       - Cloud Storage FUSE Volume Mount           │
        │       - Persists /sessions, /profiles, tokens     │
        │       - Cost: $0.00 (5 GB free tier forever)      │
        └───────────────────────────────────────────────────┘
```

---

## Part 1: Deploy the Backend to Google Cloud Run

### Step 1: Install & Set Up Google Cloud CLI
If you don't already have `gcloud` installed, [download it here](https://cloud.google.com/sdk/docs/install) (or use the web Google Cloud Shell in your browser console):
```bash
gcloud auth login
gcloud config set project <YOUR_GCP_PROJECT_ID>
```

### Step 2: Enable GCP Services & Create Artifact Registry
```bash
# Enable Cloud Run, Artifact Registry, and Cloud Storage
gcloud services enable run.googleapis.com artifactregistry.googleapis.com storage.googleapis.com

# Create a Docker repository in your preferred region (e.g., us-central1)
gcloud artifacts repositories create resume-repo \
    --repository-format=docker \
    --location=us-central1 \
    --description="Resume Maker Container Repository"
```

### Step 3: Create Persistent GCS Bucket for Database Storage
Because Cloud Run containers are serverless and spin down to 0, mount a Google Cloud Storage bucket so user profiles, chat sessions, and resumes are permanently saved:
```bash
# 1. Create the bucket (replace with your project ID)
gcloud storage buckets create gs://<YOUR_GCP_PROJECT_ID>-resume-data \
    --location=us-central1 \
    --uniform-bucket-level-access

# 2. Get your GCP project number
PROJECT_NUMBER=$(gcloud projects describe <YOUR_GCP_PROJECT_ID> --format='value(projectNumber)')

# 3. Grant Cloud Run permission to read and write to the bucket
gcloud storage buckets add-iam-policy-binding gs://<YOUR_GCP_PROJECT_ID>-resume-data \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role="roles/storage.objectAdmin"
```

### Step 4: Build & Submit the Backend Docker Image
From the root of the `resume_maker` repository:
```bash
gcloud builds submit --tag us-central1-docker.pkg.dev/<YOUR_GCP_PROJECT_ID>/resume-repo/resume-backend:latest .
```

### Step 5: Deploy to Cloud Run with GCS Volume Mount
Deploy the container with settings optimized for 100 concurrent users (2 vCPU, 4 GB RAM, auto-scaling, and the GCS bucket mounted at `/app/backend/data`):

```bash
gcloud run deploy resume-backend \
    --image us-central1-docker.pkg.dev/<YOUR_GCP_PROJECT_ID>/resume-repo/resume-backend:latest \
    --platform managed \
    --region us-central1 \
    --allow-unauthenticated \
    --execution-environment gen2 \
    --cpu 2 \
    --memory 4Gi \
    --concurrency 40 \
    --timeout 120 \
    --min-instances 0 \
    --max-instances 10 \
    --add-volume=name=resume-data-vol,type=cloud-storage,bucket=<YOUR_GCP_PROJECT_ID>-resume-data \
    --add-volume-mount=volume=resume-data-vol,mount-path=/app/backend/data \
    --set-env-vars "SESSION_SECRET=$(openssl rand -hex 32)" \
    --set-env-vars "GROQ_API_KEY=your_groq_api_key_here" \
    --set-env-vars "LLM_PROVIDER=groq" \
    --set-env-vars "MODEL_NAME=openai/gpt-oss-120b" \
    --set-env-vars "REQUIRE_AUTH_FOR_SESSIONS=true" \
    --set-env-vars "PDF_CACHE_ENABLED=1" \
    --set-env-vars "MAX_CONCURRENT_COMPILES=6"
```

> 💡 **Save your Backend URL!**
> Cloud Run will output a Service URL upon completion:
> `Service URL: https://resume-backend-xyz-uc.a.run.app`

Test that it is healthy:
```bash
curl https://resume-backend-xyz-uc.a.run.app/health
# Response: {"status":"ok","environment":"production"}
```

---

## Part 2: Deploy the Frontend to Vercel

### Step 1: Push Your Code to GitHub
Ensure all recent changes are committed and pushed:
```bash
git add .
git commit -m "Configure Vercel and Cloud Run deployment"
git push origin main
```

### Step 2: Import into Vercel
1. Log in to [Vercel.com](https://vercel.com).
2. Click **"Add New..."** ➔ **"Project"**.
3. Select your `resume_maker` repository and click **Import**.

### Step 3: Configure Project Settings on Vercel
* **Framework Preset**: `Vite` (auto-detected).
* **Root Directory**: Click *Edit* and select **`frontend`**.
* **Build Command**: `npm run build` (default).
* **Output Directory**: `dist` (default).

### Step 4: Set Environment Variable
Under **Environment Variables**, add:
* **Key**: `VITE_API_BASE_URL`
* **Value**: `https://resume-backend-xyz-uc.a.run.app` *(Your Cloud Run URL from Part 1, without trailing slash)*

### Step 5: Click Deploy!
Vercel will build your frontend in ~30 seconds and provide your live production URL:
`https://your-project.vercel.app`

---

## Part 3: Alternative — Single VM Deployment (Oracle Always Free / VPS)

If you prefer deploying everything (Nginx + Frontend + Backend + Redis) onto a single VM (e.g. Oracle Cloud 4 OCPU / 24 GB RAM Always Free instance or DigitalOcean):

1. SSH into the server:
   ```bash
   ssh user@your-vm-ip
   ```
2. Clone repo and create environment file:
   ```bash
   git clone <repo-url>
   cd resume_maker
   cp .env.production.template .env.production
   nano .env.production   # add SESSION_SECRET and LLM keys
   ```
3. Run the automated deployment script:
   ```bash
   chmod +x scripts/deploy.sh
   ./scripts/deploy.sh
   ```
4. Access your app at `http://your-vm-ip`.

---

## 📊 Summary: Scaling & Cost Reference

| Metric | When Idle (0 Users) | During 100-User Active Surge |
| :--- | :--- | :--- |
| **Vercel (Frontend)** | **$0.00** | **$0.00** (Unlimited CDN bandwidth on Hobby) |
| **Cloud Run (Backend)** | **$0.00** (Scales to 0 instances) | **~$0.84 / hour** (Spins up 3–5 instances dynamically) |
| **Tectonic LaTeX Caching** | Cached in memory / disk | **SHA-256 PDF Cache** returns identical documents in **<10ms** |
| **First-page load speed** | **<50ms** globally via Vercel | **<50ms** globally via Vercel |
