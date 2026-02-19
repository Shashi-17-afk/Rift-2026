"""
explanation_service.py — LLM-powered explanation generator.

Sends a structured pharmacogenomic summary to an OpenAI-compatible LLM
and returns a human-readable explanation.

Graceful degradation:
  - On any error (timeout, rate-limit, missing API key, etc.) the service
    returns a deterministic fallback message instead of propagating an
    exception, so the overall /api/analyze endpoint always returns a
    complete response.

Configuration (via config.py / .env):
  OPENAI_API_KEY   — required for live calls
  OPENAI_BASE_URL  — default https://api.openai.com/v1
  LLM_MODEL        — default gpt-4o-mini
  LLM_TIMEOUT_SECONDS — default 30
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app import config
from app.models.schemas import LLMExplanation, PharmacogenomicProfile, RiskAssessment

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a clinical pharmacogenomics expert. "
    "Write a concise, jargon-free paragraph (3–5 sentences) that explains "
    "the patient's pharmacogenomic result, what it means for their drug therapy, "
    "and the key clinical action. Avoid bullet points. Address the patient "
    "and their clinician jointly. Be factual and evidence-based."
)


# Helper to ensure phenotype is expanded to full label if only abbreviation is available

def _expand_phenotype_label(phenotype: str) -> str:
    mapping = {
        "PM": "Poor Metabolizer",
        "IM": "Intermediate Metabolizer",
        "NM": "Normal Metabolizer",
        "RM": "Rapid Metabolizer",
        "URM": "Ultrarapid Metabolizer",
        "Unknown": "Unknown",
    }
    return mapping.get(phenotype, phenotype)


def _build_user_prompt(
    drug: str,
    risk: RiskAssessment,
    profile: PharmacogenomicProfile,
    clinical_recommendation: dict[str, Any],
) -> str:
    variants_summary = ", ".join(
        f"{v.rsid or 'unknown rsID'} ({v.gene} {v.ref}>{v.alt})"
        for v in profile.detected_variants[:5]   # cap at 5 to stay concise
    ) or "No pharmacogenomic variants detected"

    phenotype_full = clinical_recommendation.get("phenotype_full") or profile.phenotype
    phenotype_full = _expand_phenotype_label(phenotype_full)

    return (
        f"Drug: {drug}\n"
        f"Primary Gene: {profile.primary_gene}\n"
        f"Diplotype: {profile.diplotype}\n"
        f"Phenotype: {phenotype_full} ({profile.phenotype})\n"
        f"Risk Label: {risk.risk_label}  Severity: {risk.severity}  "
        f"Confidence: {risk.confidence_score:.0%}\n"
        f"Detected Variants: {variants_summary}\n"
        f"Dose Recommendation: {clinical_recommendation.get('dose_recommendation', '')}\n"
        f"Monitoring: {clinical_recommendation.get('monitoring', '')}\n"
        f"Rationale: {clinical_recommendation.get('rationale', '')}\n\n"
        "Please write the clinical explanation paragraph now."
    )


# ---------------------------------------------------------------------------
# Fallback explanation builder (no LLM needed)
# ---------------------------------------------------------------------------

def _build_fallback_explanation(
    drug: str,
    risk: RiskAssessment,
    profile: PharmacogenomicProfile,
    clinical_recommendation: dict[str, Any],
) -> str:
    """
    Construct a deterministic, rule-based explanation when the LLM is
    unavailable. This ensures the API always returns a meaningful summary.
    """
    sev_key = (risk.severity or "").strip().lower()
    severity_adverb = {
        "critical": "critically",
        "high":     "significantly",
        "moderate": "moderately",
        "low":      "minimally",
        "none":     "negligibly",
    }.get(sev_key, "potentially")

    phenotype_full = clinical_recommendation.get("phenotype_full") or profile.phenotype
    phenotype_full = _expand_phenotype_label(phenotype_full)
    recommendation = clinical_recommendation.get(
        "dose_recommendation",
        "Please consult your prescriber for dosing guidance.",
    )
    monitoring = clinical_recommendation.get("monitoring", "")

    lines = [
        f"Based on your genetic profile, your {profile.primary_gene} diplotype "
        f"is {profile.diplotype}, which indicates a {phenotype_full} ({profile.phenotype}) status.",

        f"This {severity_adverb} affects how your body processes {drug.title()}, "
        f"resulting in a '{risk.risk_label}' risk classification "
        f"(confidence {risk.confidence_score:.0%}).",

        recommendation,
    ]
    if monitoring:
        lines.append(f"Monitoring guidance: {monitoring}")

    lines.append(
        "Please discuss these findings with your healthcare provider before "
        "making any changes to your medication."
    )

    return " ".join(lines)


# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------

async def _call_llm(prompt_user: str) -> str:
    """
    Send a chat-completion request to the configured LLM endpoint.
    Returns the assistant message text.
    Raises httpx.HTTPError or httpx.TimeoutException on failure.
    """
    headers = {
        "Authorization": f"Bearer {config.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.LLM_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": prompt_user},
        ],
        "temperature": 0.4,
        "max_tokens": 300,
    }
    url = f"{config.OPENAI_BASE_URL.rstrip('/')}/chat/completions"

    async with httpx.AsyncClient(timeout=config.LLM_TIMEOUT_SECONDS) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_explanation(
    drug: str,
    risk: RiskAssessment,
    profile: PharmacogenomicProfile,
    clinical_recommendation: dict[str, Any],
) -> LLMExplanation:
    """
    Generate a human-readable pharmacogenomic explanation.

    Attempts an LLM call first; on any failure falls back to a
    deterministic rule-based summary so the API response is never blocked.

    Args:
        drug: Drug name (e.g. "WARFARIN").
        risk: RiskAssessment from risk_engine.
        profile: PharmacogenomicProfile from risk_engine.
        clinical_recommendation: clinical_recommendation dict from risk_engine.

    Returns:
        LLMExplanation with a summary string.
    """
    # Skip LLM call if no API key is configured
    if not config.OPENAI_API_KEY:
        logger.info("OPENAI_API_KEY not set — using fallback explanation.")
        summary = _build_fallback_explanation(drug, risk, profile, clinical_recommendation)
        return LLMExplanation(summary=summary)

    user_prompt = _build_user_prompt(drug, risk, profile, clinical_recommendation)

    try:
        summary = await _call_llm(user_prompt)
        logger.info("LLM explanation generated successfully (%d chars).", len(summary))
        return LLMExplanation(summary=summary)

    except httpx.TimeoutException:
        logger.warning("LLM call timed out after %ds — using fallback.", config.LLM_TIMEOUT_SECONDS)
    except httpx.HTTPStatusError as exc:
        logger.warning("LLM HTTP error %s — using fallback.", exc.response.status_code)
    except Exception as exc:  # noqa: BLE001
        logger.error("Unexpected LLM error: %s — using fallback.", exc)

    # Graceful fallback
    summary = _build_fallback_explanation(drug, risk, profile, clinical_recommendation)
    return LLMExplanation(summary=summary)
