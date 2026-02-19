"""
Pydantic models matching the exact JSON output schema.
Used for response validation and API documentation.
"""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


# --- Response schema (exact match to required JSON output) ---


class RiskAssessment(BaseModel):
    """Risk assessment for the drug-gene interaction."""

    risk_label: str = ""
    confidence_score: float = Field(ge=0.0, le=1.0, default=0.0)
    severity: str = ""


class VariantInfo(BaseModel):
    """Single detected variant in pharmacogenomic profile."""

    gene: str = ""
    chromosome: str = ""
    position: int = 0
    ref: str = ""
    alt: str = ""
    rsid: str | None = None


class PharmacogenomicProfile(BaseModel):
    """Pharmacogenomic profile derived from VCF variants."""

    primary_gene: str = ""
    diplotype: str = ""
    phenotype: str = ""
    detected_variants: list[VariantInfo] = Field(default_factory=list)


class LLMExplanation(BaseModel):
    """LLM-generated human-readable explanation."""

    summary: str = ""


class QualityMetrics(BaseModel):
    """Quality and processing metadata."""

    vcf_parsing_success: bool = True


# --- Request schema (for /api/analyze form validation) ---


class AnalyzeRequest(BaseModel):
    """
    Form fields for VCF analysis.
    File is passed separately as UploadFile.
    """

    patient_id: str = Field(..., min_length=1, description="Patient identifier (e.g. PATIENT_001)")
    drug: str = Field(..., description="Drug name from supported list")


class FullResponse(BaseModel):
    """Complete API response matching the required JSON schema."""

    patient_id: str
    drug: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    risk_assessment: RiskAssessment = Field(default_factory=RiskAssessment)
    pharmacogenomic_profile: PharmacogenomicProfile = Field(default_factory=PharmacogenomicProfile)
    clinical_recommendation: dict[str, Any] = Field(default_factory=dict)
    llm_generated_explanation: LLMExplanation = Field(default_factory=LLMExplanation)
    quality_metrics: QualityMetrics = Field(default_factory=QualityMetrics)
