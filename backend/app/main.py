"""
main.py — PharmaGuard FastAPI application.

Routes
------
GET  /health          — liveness probe
GET  /api/test        — mock response (no VCF required)
POST /api/analyze     — full analysis pipeline (VCF upload)

Data flow (POST /api/analyze)
------------------------------
1. Validate multipart form fields (patient_id, drug, file).
2. vcf_parser      → ParseResult (list of raw variant dicts)
3. variant_extractor → list[VariantInfo] filtered by primary gene
4. risk_engine      → RiskAssessment, PharmacogenomicProfile, clinical_recommendation
5. explanation_service → LLMExplanation (LLM or deterministic fallback)
6. Assemble FullResponse and return validated JSON.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import config
from app.models.schemas import (
    FullResponse,
    LLMExplanation,
    PharmacogenomicProfile,
    QualityMetrics,
    RiskAssessment,
    VariantInfo,
)
from app.services.explanation_service import generate_explanation
from app.services.risk_engine import assess_risk
from app.services.variant_extractor import extract_variants
from app.services.vcf_parser import parse_vcf_bytes
from app.utils.exceptions import (
    DrugNotSupportedError,
    FileValidationError,
    PharmaGuardError,
    VCFParseError,
    register_exception_handlers,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="PharmaGuard API",
    description=(
        "Pharmacogenomics backend: parse VCF files, extract gene variants, "
        "assess drug risk, and return structured clinical guidance."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — open for development; tighten for production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register custom exception handlers
register_exception_handlers(app)


# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup_event() -> None:
    logger.info("PharmaGuard API starting up.")
    logger.info("Supported drugs: %s", sorted(config.SUPPORTED_DRUGS))
    logger.info("Supported genes: %s", sorted(config.SUPPORTED_GENES))
    if not config.OPENAI_API_KEY:
        logger.warning(
            "OPENAI_API_KEY not set — explanation service will use fallback mode."
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_drug(drug: str) -> str:
    """Normalise drug to uppercase and confirm it is supported."""
    drug_upper = drug.strip().upper()
    if drug_upper not in config.SUPPORTED_DRUGS:
        raise DrugNotSupportedError(drug_upper)
    return drug_upper


def _validate_file(file: UploadFile) -> None:
    """Check file extension and content-type."""
    filename = file.filename or ""
    # Accept .vcf, .vcf.gz, .bcf
    lower = filename.lower()
    if not any(lower.endswith(ext) for ext in config.ALLOWED_VCF_EXTENSIONS):
        raise FileValidationError(
            f"Unsupported file type '{Path(filename).suffix}'. "
            f"Allowed: {', '.join(config.ALLOWED_VCF_EXTENSIONS)}"
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _build_empty_response(patient_id: str, drug: str, *, parsing_success: bool) -> FullResponse:
    """Return a FullResponse shell when VCF parsing fails."""
    return FullResponse(
        patient_id=patient_id,
        drug=drug,
        timestamp=_now_iso(),
        risk_assessment=RiskAssessment(),
        pharmacogenomic_profile=PharmacogenomicProfile(),
        clinical_recommendation={},
        llm_generated_explanation=LLMExplanation(
            summary="VCF parsing failed. No pharmacogenomic assessment could be performed."
        ),
        quality_metrics=QualityMetrics(vcf_parsing_success=parsing_success),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get(
    "/health",
    summary="Health check",
    tags=["Utility"],
    response_model=dict,
)
async def health_check() -> dict[str, Any]:
    """Simple liveness probe. Returns 200 when the server is up."""
    return {
        "status": "healthy",
        "service": "PharmaGuard API",
        "version": "1.0.0",
        "timestamp": _now_iso(),
        "supported_drugs": sorted(config.SUPPORTED_DRUGS),
        "supported_genes": sorted(config.SUPPORTED_GENES),
    }


# ---------------------------------------------------------------------------
# GET /api/test — returns a fully-formed mock response with no VCF required
# ---------------------------------------------------------------------------

@app.get(
    "/api/test",
    summary="Mock test response",
    tags=["API"],
    response_model=FullResponse,
)
async def test_endpoint() -> FullResponse:
    """
    Returns a pre-built mock FullResponse representing a WARFARIN / CYP2C9
    Poor Metabolizer case. Useful for frontend integration and schema validation
    without uploading a real VCF.
    """
    mock_variants = [
        VariantInfo(
            gene="CYP2C9",
            chromosome="10",
            position=96741053,
            ref="C",
            alt="T",
            rsid="rs1799853",
        ),
        VariantInfo(
            gene="CYP2C9",
            chromosome="10",
            position=96740980,
            ref="A",
            alt="C",
            rsid="rs1057910",
        ),
    ]
    return FullResponse(
        patient_id="TEST_PATIENT_001",
        drug="WARFARIN",
        timestamp=_now_iso(),
        risk_assessment=RiskAssessment(
            risk_label="Toxic",
            confidence_score=0.93,
            severity="high",
        ),
        pharmacogenomic_profile=PharmacogenomicProfile(
            primary_gene="CYP2C9",
            diplotype="*2/*3",
            phenotype="PM",
            detected_variants=mock_variants,
        ),
        clinical_recommendation={
            "drug": "WARFARIN",
            "gene": "CYP2C9",
            "phenotype": "PM",
            "phenotype_full": "Poor Metabolizer",
            "dose_recommendation": (
                "Initiate at ≤25% of standard warfarin dose. "
                "Expect prolonged time to stable INR."
            ),
            "monitoring": "INR every 3 days for first 2 weeks; then weekly until stable.",
            "rationale": (
                "Severely reduced CYP2C9 activity causes warfarin accumulation "
                "and elevated bleeding risk."
            ),
        },
        llm_generated_explanation=LLMExplanation(
            summary=(
                "Your genetic profile shows a CYP2C9 *2/*3 diplotype (Poor Metabolizer — PM). "
                "Your body metabolises warfarin much more slowly than average, significantly "
                "increasing the risk of warfarin accumulation and bleeding if standard doses are used. "
                "Your clinician should initiate therapy at no more than 25% of the typical dose "
                "and monitor your INR every three days during the first two weeks. "
                "Discuss these results with your prescriber before starting or adjusting warfarin therapy."
            ),
        ),
        quality_metrics=QualityMetrics(vcf_parsing_success=True),
    )


# ---------------------------------------------------------------------------
# POST /api/analyze — main analysis pipeline
# ---------------------------------------------------------------------------

@app.post(
    "/api/analyze",
    summary="Analyse VCF for pharmacogenomic drug risk",
    tags=["API"],
    response_model=FullResponse,
    status_code=status.HTTP_200_OK,
)
async def analyze(
    patient_id: str = Form(..., description="Patient identifier, e.g. PATIENT_001"),
    drug: str = Form(..., description="Drug name — one of: CODEINE, WARFARIN, CLOPIDOGREL, SIMVASTATIN, AZATHIOPRINE, FLUOROURACIL"),
    file: UploadFile = File(..., description="VCF file (.vcf or .vcf.gz)"),
) -> FullResponse:
    """
    Full pharmacogenomic analysis pipeline.

    1. Validates request fields and file type.
    2. Parses the uploaded VCF with PyVCF3.
    3. Extracts variants relevant to the drug's primary gene.
    4. Runs the risk engine to determine diplotype, phenotype, and risk.
    5. Calls the LLM explanation service (falls back gracefully on failure).
    6. Returns a validated FullResponse JSON.
    """
    # ------------------------------------------------------------------
    # 1. Input validation
    # ------------------------------------------------------------------
    patient_id = patient_id.strip()
    if not patient_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="patient_id must not be empty.",
        )

    drug_upper = _validate_drug(drug)         # raises DrugNotSupportedError if invalid
    _validate_file(file)                       # raises FileValidationError if invalid

    # ------------------------------------------------------------------
    # 2. Read file — enforce size limit
    # ------------------------------------------------------------------
    vcf_bytes = await file.read()
    if len(vcf_bytes) > config.MAX_VCF_SIZE_BYTES:
        raise FileValidationError(
            f"VCF file exceeds maximum allowed size of {config.MAX_VCF_SIZE_MB} MB."
        )
    if len(vcf_bytes) == 0:
        raise FileValidationError("Uploaded VCF file is empty.")

    logger.info(
        "Received /api/analyze: patient=%s drug=%s file=%s size=%d bytes",
        patient_id, drug_upper, file.filename, len(vcf_bytes),
    )

    # ------------------------------------------------------------------
    # 3. VCF parsing
    # ------------------------------------------------------------------
    try:
        parse_result = parse_vcf_bytes(vcf_bytes)
    except VCFParseError as exc:
        logger.warning("VCF parse failed for patient %s: %s", patient_id, exc.message)
        return _build_empty_response(patient_id, drug_upper, parsing_success=False)

    logger.info(
        "Parsed %d variants for patient %s", parse_result.variant_count, patient_id
    )

    # ------------------------------------------------------------------
    # 4. Variant extraction  (filter by primary gene for the drug)
    # ------------------------------------------------------------------
    primary_gene = config.DRUG_TO_GENE[drug_upper]

    try:
        detected_variants = extract_variants(parse_result.variants, primary_gene)
    except Exception as exc:  # noqa: BLE001
        logger.error("Variant extraction error: %s", exc)
        detected_variants = []

    logger.info(
        "Extracted %d variants for gene %s", len(detected_variants), primary_gene
    )

    # ------------------------------------------------------------------
    # 5. Risk assessment
    # ------------------------------------------------------------------
    try:
        risk_assessment, pgx_profile, clinical_rec = assess_risk(
            drug=drug_upper,
            gene=primary_gene,
            detected_variants=detected_variants,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Risk engine error: %s", exc)
        risk_assessment = RiskAssessment()
        pgx_profile = PharmacogenomicProfile(
            primary_gene=primary_gene,
            detected_variants=detected_variants,
        )
        clinical_rec = {}

    # ------------------------------------------------------------------
    # 6. LLM explanation (async, never raises)
    # ------------------------------------------------------------------
    llm_explanation = await generate_explanation(
        drug=drug_upper,
        risk=risk_assessment,
        profile=pgx_profile,
        clinical_recommendation=clinical_rec,
    )

    # ------------------------------------------------------------------
    # 7. Assemble and validate response
    # ------------------------------------------------------------------
    response = FullResponse(
        patient_id=patient_id,
        drug=drug_upper,
        timestamp=_now_iso(),
        risk_assessment=risk_assessment,
        pharmacogenomic_profile=pgx_profile,
        clinical_recommendation=clinical_rec,
        llm_generated_explanation=llm_explanation,
        quality_metrics=QualityMetrics(vcf_parsing_success=parse_result.success),
    )

    logger.info(
        "Analysis complete: patient=%s drug=%s risk=%s phenotype=%s",
        patient_id, drug_upper,
        risk_assessment.risk_label,
        pgx_profile.phenotype,
    )

    return response


# ---------------------------------------------------------------------------
# Generic HTTP-exception fallback (for anything FastAPI raises internally)
# ---------------------------------------------------------------------------

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "error_type": "HTTPException"},
    )
