# PharmaGuard 🧬🛡️

> **Pharmacogenomic Risk Analysis — AI-powered, CPIC-guided gene–drug assessment from a VCF file in seconds.**

PharmaGuard parses a patient's genomic VCF file, extracts variants for a target gene, maps them through CPIC star-allele tables to a diplotype and phenotype, and returns a structured clinical risk report with an AI-generated human-readable explanation.

---

## ✨ Features

| Feature | Detail |
|---|---|
| **VCF Parsing** | PyVCF3 — accepts `.vcf`, `.vcf.gz`, `.bcf` up to 50 MB |
| **Variant Extraction** | Annotation-based (CSQ/ANN/GENEINFO) + coordinate-based fallback (hg19) |
| **Risk Engine** | CPIC star-allele tables → diplotype → phenotype → risk label / severity / confidence |
| **AI Explanation** | OpenAI-compatible LLM (graceful fallback when API key absent) |
| **6 Gene–Drug Pairs** | CYP2D6/Codeine · CYP2C9/Warfarin · CYP2C19/Clopidogrel · SLCO1B1/Simvastatin · TPMT/Azathioprine · DPYD/Fluorouracil |
| **Modern Frontend** | Dark glassmorphism UI — drag-and-drop upload, animated DNA spinner, per-gene result cards |
| **Demo Mode** | One click — no VCF needed |
| **Docker-ready** | Single `docker compose up` starts both backend and frontend |

---

## 🗂️ Project Structure

```
Hackathon Winners/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app — routes, startup, wiring
│   │   ├── config.py               # Settings, gene/drug constants
│   │   ├── models/
│   │   │   └── schemas.py          # Pydantic request / response models
│   │   ├── services/
│   │   │   ├── vcf_parser.py       # PyVCF3 parsing → raw variant dicts
│   │   │   ├── variant_extractor.py# Filter variants by gene
│   │   │   ├── risk_engine.py      # Star-allele → diplotype → risk
│   │   │   └── explanation_service.py # LLM explanation (with fallback)
│   │   └── utils/
│   │       └── exceptions.py       # Custom exceptions + FastAPI handlers
│   ├── tests/
│   │   └── sample.vcf              # 6-gene test VCF (hg19 rsIDs)
│   ├── requirements.txt
│   ├── .env.example
│   └── Dockerfile
├── frontend/
│   ├── index.html                  # Single-page app
│   ├── style.css                   # Glassmorphism design system
│   ├── app.js                      # API integration + result rendering
│   └── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## 🚀 Quick Start

### Option A — Docker (recommended)

```bash
# 1. Clone / unzip the project
cd "Hackathon Winners"

# 2. (Optional) Add your OpenAI key for LLM explanations
cp backend/.env.example backend/.env
# Edit backend/.env → set OPENAI_API_KEY=sk-...

# 3. Start everything
docker compose up --build

# Frontend → http://localhost:3000
# Backend  → http://localhost:8000
# API Docs → http://localhost:8000/docs
```

### Option B — Local Python

```powershell
# Backend
cd "Hackathon Winners\backend"
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env          # edit OPENAI_API_KEY if desired
python -m uvicorn app.main:app --reload --port 8000

# Frontend (new terminal)
cd "Hackathon Winners\frontend"
python -m http.server 3000
```

Open **http://localhost:3000** in your browser.

---

## 🌐 API Reference

### `GET /health`
Liveness probe. Returns status, version, and supported drugs/genes.

```json
{
  "status": "healthy",
  "service": "PharmaGuard API",
  "version": "1.0.0",
  "timestamp": "2026-02-19T11:46:37Z",
  "supported_drugs": ["AZATHIOPRINE", "CLOPIDOGREL", "CODEINE", "FLUOROURACIL", "SIMVASTATIN", "WARFARIN"],
  "supported_genes": ["CYP2C19", "CYP2C9", "CYP2D6", "DPYD", "SLCO1B1", "TPMT"]
}
```

---

### `GET /api/test`
Returns a pre-built mock response (Warfarin / CYP2C9 `Toxic`). No file upload required.

```bash
curl http://localhost:8000/api/test
```

---

### `POST /api/analyze`
Full analysis pipeline.

**Form fields**

| Field | Type | Required | Description |
|---|---|---|---|
| `patient_id` | string | ✅ | Patient identifier e.g. `PATIENT_001` |
| `drug` | string | ✅ | One of `WARFARIN`, `CODEINE`, `CLOPIDOGREL`, `SIMVASTATIN`, `AZATHIOPRINE`, `FLUOROURACIL` |
| `file` | file | ✅ | VCF file (`.vcf`, `.vcf.gz`, `.bcf`) — max 50 MB |

**Example — Python**

```python
import httpx

with open("backend/tests/sample.vcf", "rb") as f:
    resp = httpx.post(
        "http://localhost:8000/api/analyze",
        data={"patient_id": "PATIENT_001", "drug": "WARFARIN"},
        files={"file": ("sample.vcf", f, "text/plain")},
    )
print(resp.json())
```

**Example — curl**

```bash
curl -X POST http://localhost:8000/api/analyze \
  -F "patient_id=PATIENT_001" \
  -F "drug=WARFARIN" \
  -F "file=@backend/tests/sample.vcf"
```

---

### Response Schema

```jsonc
{
  "patient_id": "PATIENT_001",
  "drug": "WARFARIN",
  "timestamp": "2026-02-19T11:46:37Z",
  "risk_assessment": {
    "risk_label": "Toxic",              // Safe | Adjust Dosage | Toxic | Ineffective | Unknown
    "confidence_score": 0.93,          // 0.0 – 1.0
    "severity": "high"                 // none | low | moderate | high | critical
  },
  "pharmacogenomic_profile": {
    "primary_gene": "CYP2C9",
    "diplotype": "*2/*3",
    "phenotype": "PM",                  // PM | IM | NM | RM | URM | Unknown
    "detected_variants": [
      {
        "gene": "CYP2C9",
        "chromosome": "10",
        "position": 96741053,
        "ref": "C",
        "alt": "T",
        "rsid": "rs1799853"
      }
    ]
  },
  "clinical_recommendation": {
    "dose_recommendation": "Initiate at ≤25% of standard warfarin dose...",
    "monitoring": "INR every 3 days for first 2 weeks...",
    "rationale": "Severely reduced CYP2C9 activity causes warfarin accumulation..."
  },
  "llm_generated_explanation": {
    "summary": "Your genetic profile shows a CYP2C9 *2/*3 diplotype..."
  },
  "quality_metrics": {
    "vcf_parsing_success": true
  }
}
```

---

## 🧬 Gene–Drug Coverage

| Drug | Gene | Risk Phenotypes |
|---|---|---|
| Warfarin | CYP2C9 | Poor · Intermediate · Normal Metabolizer |
| Codeine | CYP2D6 | Poor · Intermediate · Normal · Ultrarapid Metabolizer |
| Clopidogrel | CYP2C19 | Poor · Intermediate · Normal · Rapid · Ultrarapid Metabolizer |
| Simvastatin | SLCO1B1 | Poor Function · Decreased Function · Normal Function |
| Azathioprine | TPMT | Poor · Intermediate · Normal Metabolizer |
| Fluorouracil | DPYD | No Activity · Severely Decreased · Intermediate · Normal Metabolizer |

---

## ⚙️ Configuration

Copy `backend/.env.example` → `backend/.env` and edit:

```env
# LLM explanation (optional — fallback mode used when absent)
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
LLM_TIMEOUT_SECONDS=30

# Upload limits
MAX_VCF_SIZE_MB=50
```

When `OPENAI_API_KEY` is not set, the backend generates a deterministic rule-based explanation instead of calling the LLM — the API always returns a complete response.

---

## 🧪 Testing

```bash
cd "Hackathon Winners/backend"

# Smoke-test all 6 drugs against sample.vcf (server must be running)
python tests/smoke_test.py
```

Expected output:

```
DRUG             DIPLOTYPE      PHENOTYPE    RISK             CONF
------------------------------------------------------------------------
CODEINE          *4/*1          IM           Adjust Dosage    78%
WARFARIN         *2/*3          IM           Adjust Dosage    80%
CLOPIDOGREL      *2/*1          IM           Adjust Dosage    76%
SIMVASTATIN      *5/*1          IM           Adjust Dosage    77%
AZATHIOPRINE     *3B/*1         IM           Adjust Dosage    82%
FLUOROURACIL     *2A/*1         IM           Adjust Dosage    78%
```

---

## 🏗️ Architecture / Data Flow

```
POST /api/analyze
      │
      ▼
  Validate (patient_id, drug, file type/size)
      │
      ▼
  vcf_parser.parse_vcf_bytes()          ← PyVCF3
      │  ParseResult {variants, success}
      ▼
  variant_extractor.extract_variants()  ← annotation → coordinate fallback
      │  list[VariantInfo]
      ▼
  risk_engine.assess_risk()             ← rsID lookup → diplotype → phenotype → rules
      │  RiskAssessment, PharmacogenomicProfile, clinical_recommendation
      ▼
  explanation_service.generate_explanation()  ← LLM (or deterministic fallback)
      │  LLMExplanation
      ▼
  FullResponse (Pydantic-validated JSON)
```

---

## 📄 License

MIT — built for hackathon demonstration purposes. Results do not constitute medical advice.
#   R i f t - 2 0 2 6  
 