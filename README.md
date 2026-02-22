# AI LaTeX Resume Maker

A professional, AI-powered resume builder that bridges the gap between AI-driven content generation and high-quality LaTeX typesetting.

## 🚀 Features

- **Gemini-Powered Engine**: Uses Gemini 1.5 Pro for content generation, JD optimization, and self-correcting LaTeX compilation.
- **Artifacts UI**: A Claude-style split-screen interface with a real-time Chat interface and a PDF/Source code preview.
- **ATS Radar**: Semantic matching and AI-driven keyword extraction using Gemini embeddings (`text-embedding-004`).
- **Robust Sectional Editing**: Granularly edit specific resume sections without affecting the rest of the document.
- **Self-Correction Loop**: Automatically repairs common LaTeX compilation errors via an AI-driven feedback loop.
- **Direct Source Editing**: Edit LaTeX source code manually and use the "Sync & Render" feature to update the PDF instantly.

## 🏗️ Technical Architecture

### Backend (Python/FastAPI)
- **Core Engine**: FastAPI for asynchronous request handling.
- **AI Agent**: Orchestrates Gemini API calls for structured JSON outputs.
- **Compiler**: Uses the **Tectonic** LaTeX engine for fast, non-interactive PDF generation.
- **Parser**: A custom robust regex-based parser for managing sectional LaTeX updates.
- **Scorer**: Calculates job match percentages using cosine similarity of Gemini embeddings.

### Frontend (React/Vite)
- **UI Components**: Built with Tailwind CSS and Framer Motion for a premium, responsive aesthetic.
- **Editor**: Uses `AceEditor` for high-performance LaTeX syntax highlighting and source editing.
- **Icons**: Powered by `lucide-react`.
- **Animations**: Fluid transitions and premium dark-mode styling.

## 🛠️ Setup Instructions

### Prerequisites
- Docker & Docker Compose (for Containerized)
- Python 3.9+ & Node.js 18+ (for Local Dev)
- Tectonic installed on host ([Installation Guide](https://tectonic-typesetting.org/install/))
- Gemini API Key

### Option 1: Containerized (Fastest)
```bash
docker-compose up --build
```
The application will be available at `http://localhost:3000`.

### Option 2: Local Development (Best for iteration)

1. **Environment Setup**:
   - Create a `.env` file in the root:
     ```env
     GEMINI_API_KEY=your_key_here
     ```

2. **Backend**:
   ```bash
   cd backend
   python -m venv venv
   .\venv\Scripts\activate  # Windows
   pip install -r requirements.txt
   python main.py
   ```
   Backend runs at `http://localhost:8000`.

3. **Frontend**:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
   Frontend runs at `http://localhost:3000` with automated proxy to backend.

## 📂 Project Structure

```text
resume_maker/
├── backend/
│   ├── core/           # Business logic (AI, Compiler, Parser, Scaler)
│   ├── templates/      # LaTeX template library
│   └── main.py         # API entry point
├── frontend/
│   ├── src/            # React application source
│   └── vite.config.js  # Build and proxy config
└── docker-compose.yml  # Orchestration
```

## 📝 License
MIT
