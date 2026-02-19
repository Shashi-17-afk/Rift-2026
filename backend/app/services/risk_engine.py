"""
risk_engine.py — Pharmacogenomic risk assessment service.

Output schema (RIFT 2026 required):
  risk_label : "Safe" | "Adjust Dosage" | "Toxic" | "Ineffective" | "Unknown"
  severity   : "none" | "low" | "moderate" | "high" | "critical"
  phenotype  : "PM" | "IM" | "NM" | "RM" | "URM" | "Unknown"

References: CPIC guidelines (cpicpgx.org), PharmGKB.
"""

from __future__ import annotations

import logging
from typing import Any

from app.models.schemas import (
    PharmacogenomicProfile,
    RiskAssessment,
    VariantInfo,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Star-allele rsID lookup tables
# activity: "none" | "reduced" | "normal" | "increased"
# ---------------------------------------------------------------------------

STAR_ALLELE_RSIDS: dict[str, dict[str, tuple[str, str]]] = {
    "CYP2D6": {
        "rs3892097":  ("*4",  "none"),
        "rs5030655":  ("*6",  "none"),
        "rs16947":    ("*2",  "normal"),
        "rs1065852":  ("*10", "reduced"),
        "rs28371725": ("*41", "reduced"),
        "rs1135840":  ("*2",  "normal"),
    },
    "CYP2C9": {
        "rs1799853":  ("*2", "reduced"),
        "rs1057910":  ("*3", "none"),
        "rs28371686": ("*5", "none"),
        "rs72558187": ("*6", "none"),
    },
    "CYP2C19": {
        "rs4244285":  ("*2",  "none"),
        "rs4986893":  ("*3",  "none"),
        "rs12248560": ("*17", "increased"),
        "rs28399504": ("*4",  "none"),
    },
    "SLCO1B1": {
        "rs4149056":  ("*5",  "reduced"),
        "rs2306283":  ("*1b", "normal"),
        "rs11045819": ("*15", "reduced"),
    },
    "TPMT": {
        "rs1800460": ("*3B", "none"),
        "rs1142345": ("*3C", "none"),
        "rs1800462": ("*2",  "none"),
        "rs1800584": ("*3A", "none"),
    },
    "DPYD": {
        "rs3918290":  ("*2A",       "none"),
        "rs67376798": ("c.2846A>T", "reduced"),
        "rs55886062": ("c.1679T>G", "none"),
        "rs75017182": ("c.1236G>A", "reduced"),
    },
}


# ---------------------------------------------------------------------------
# Phenotype map: activity-pair → CPIC abbreviation
# ---------------------------------------------------------------------------

PHENOTYPE_MAP: dict[str, dict[str, str]] = {
    "CYP2D6": {
        "none+none":           "PM",
        "none+reduced":        "PM",
        "reduced+none":        "PM",   # asymmetric — still poor
        "reduced+reduced":     "IM",
        "normal+none":         "IM",
        "normal+reduced":      "IM",
        "none+increased":      "IM",   # one loss + one gain → net IM
        "increased+none":      "IM",
        "normal+normal":       "NM",
        "normal+increased":    "RM",
        "increased+normal":    "RM",
        "increased+increased": "URM",
        "default":             "NM",
    },
    "CYP2C9": {
        "none+none":       "PM",
        "reduced+none":    "IM",
        "reduced+reduced": "IM",
        "normal+none":     "IM",
        "normal+reduced":  "IM",
        "normal+normal":   "NM",
        "default":         "NM",
    },
    "CYP2C19": {
        "none+none":           "PM",
        "none+reduced":        "PM",
        "reduced+none":        "PM",
        "reduced+reduced":     "PM",  # compound heterozygous loss-of-function
        "normal+none":         "IM",
        "normal+reduced":      "IM",
        "none+increased":      "IM",  # one loss + one gain → net intermediate
        "normal+normal":       "NM",
        "normal+increased":    "RM",  # CYP2C19*17 heterozygous
        "increased+normal":    "RM",
        "increased+increased": "URM",
        "increased+none":      "IM",  # one gain + one loss → intermediate
        "default":             "NM",
    },
    "SLCO1B1": {
        "reduced+reduced": "PM",
        "none+reduced":    "PM",   # no-function allele combinations → PM
        "reduced+none":    "PM",
        "normal+reduced":  "IM",
        "reduced+normal":  "IM",
        "normal+none":     "IM",   # one no-function + normal → decreased function
        "none+normal":     "IM",
        "normal+normal":   "NM",
        "default":         "NM",
    },
    "TPMT": {
        "none+none":     "PM",
        "normal+none":   "IM",
        "normal+normal": "NM",
        "default":       "NM",
    },
    "DPYD": {
        "none+none":      "PM",
        "none+reduced":   "PM",
        "normal+none":    "IM",
        "normal+reduced": "IM",
        "normal+normal":  "NM",
        "default":        "NM",
    },
}

PHENOTYPE_FULL: dict[str, str] = {
    "PM":      "Poor Metabolizer",
    "IM":      "Intermediate Metabolizer",
    "NM":      "Normal Metabolizer",
    "RM":      "Rapid Metabolizer",
    "URM":     "Ultrarapid Metabolizer",
    "Unknown": "Unknown",
}


# ---------------------------------------------------------------------------
# Risk rules: gene+phenotype_abbr → risk
# ---------------------------------------------------------------------------

RiskRule = dict[str, Any]

RISK_RULES: dict[str, dict[str, RiskRule]] = {
    "CYP2D6": {
        "PM": {
            "risk_label": "Ineffective",
            "severity": "high",
            "confidence_score": 0.92,
            "dose_recommendation": "Avoid codeine; use non-opioid alternative or significantly reduced dose of alternative opioids.",
            "monitoring": "If opioid required, select agent not dependent on CYP2D6 (e.g., morphine, oxymorphone).",
            "rationale": "Poor CYP2D6 metabolisers cannot convert codeine to morphine adequately, risking treatment failure.",
        },
        "IM": {
            "risk_label": "Adjust Dosage",
            "severity": "moderate",
            "confidence_score": 0.78,
            "dose_recommendation": "Use with caution; consider reduced dose or alternative analgesic.",
            "monitoring": "Monitor for reduced efficacy; pain scores should be reassessed at 24 h.",
            "rationale": "Reduced CYP2D6 activity leads to diminished morphine production.",
        },
        "NM": {
            "risk_label": "Safe",
            "severity": "low",
            "confidence_score": 0.85,
            "dose_recommendation": "Standard dosing per label.",
            "monitoring": "Routine monitoring.",
            "rationale": "Normal CYP2D6 activity; codeine metabolism expected to be typical.",
        },
        "RM": {
            "risk_label": "Toxic",
            "severity": "high",
            "confidence_score": 0.88,
            "dose_recommendation": "Use lower dose; monitor for signs of opioid excess.",
            "monitoring": "Monitor respiratory rate and sedation at initiation.",
            "rationale": "Increased CYP2D6 activity converts codeine to morphine faster than normal.",
        },
        "URM": {
            "risk_label": "Toxic",
            "severity": "critical",
            "confidence_score": 0.95,
            "dose_recommendation": "CONTRAINDICATED. Ultrarapid conversion to morphine causes toxicity risk.",
            "monitoring": "Do not use; select alternative analgesic.",
            "rationale": "CYP2D6 ultrarapid metabolisers convert codeine to morphine very rapidly, risking respiratory depression.",
        },
    },
    "CYP2C9": {
        "PM": {
            "risk_label": "Toxic",
            "severity": "high",
            "confidence_score": 0.93,
            "dose_recommendation": "Initiate at ≤25% of standard warfarin dose. Expect prolonged time to stable INR.",
            "monitoring": "INR every 3 days for first 2 weeks; then weekly until stable.",
            "rationale": "Severely reduced CYP2C9 activity causes warfarin accumulation and elevated bleeding risk.",
        },
        "IM": {
            "risk_label": "Adjust Dosage",
            "severity": "moderate",
            "confidence_score": 0.80,
            "dose_recommendation": "Initiate at 50–75% of standard dose. Adjust based on INR.",
            "monitoring": "Increased INR frequency in first 4 weeks.",
            "rationale": "Partially reduced CYP2C9 activity leads to warfarin accumulation.",
        },
        "NM": {
            "risk_label": "Safe",
            "severity": "low",
            "confidence_score": 0.88,
            "dose_recommendation": "Standard dosing per label.",
            "monitoring": "Routine INR monitoring.",
            "rationale": "Normal CYP2C9 activity; standard warfarin metabolism expected.",
        },
    },
    "CYP2C19": {
        "PM": {
            "risk_label": "Ineffective",
            "severity": "high",
            "confidence_score": 0.91,
            "dose_recommendation": "Avoid clopidogrel; use prasugrel or ticagrelor if not contraindicated.",
            "monitoring": "Platelet function testing if alternative antiplatelet unavailable.",
            "rationale": "Poor CYP2C19 metabolisers fail to convert clopidogrel to active metabolite, increasing MACE risk.",
        },
        "IM": {
            "risk_label": "Adjust Dosage",
            "severity": "moderate",
            "confidence_score": 0.76,
            "dose_recommendation": "Consider alternative antiplatelet. If clopidogrel used, monitor closely.",
            "monitoring": "Platelet aggregation studies at initiation.",
            "rationale": "Partially impaired CYP2C19 activity reduces clopidogrel efficacy.",
        },
        "NM": {
            "risk_label": "Safe",
            "severity": "low",
            "confidence_score": 0.87,
            "dose_recommendation": "Standard dosing per label.",
            "monitoring": "Routine clinical monitoring.",
            "rationale": "Normal CYP2C19 activity; standard clopidogrel activation expected.",
        },
        "RM": {
            "risk_label": "Safe",
            "severity": "low",
            "confidence_score": 0.82,
            "dose_recommendation": "Standard dosing.",
            "monitoring": "Routine monitoring.",
            "rationale": "Slightly increased CYP2C19 activity; generally favourable for clopidogrel.",
        },
        "URM": {
            "risk_label": "Adjust Dosage",
            "severity": "moderate",
            "confidence_score": 0.80,
            "dose_recommendation": "Standard dosing. Enhanced antiplatelet effect possible; monitor for bleeding.",
            "monitoring": "Monitor for bleeding.",
            "rationale": "Enhanced CYP2C19 activity increases clopidogrel active metabolite.",
        },
    },
    "SLCO1B1": {
        "PM": {
            "risk_label": "Toxic",
            "severity": "high",
            "confidence_score": 0.89,
            "dose_recommendation": "Avoid simvastatin 80 mg. Use ≤20 mg simvastatin or switch to pravastatin/rosuvastatin.",
            "monitoring": "CK levels at baseline and at 6 weeks.",
            "rationale": "Severely reduced SLCO1B1 transport leads to statin accumulation and high myopathy risk.",
        },
        "IM": {
            "risk_label": "Adjust Dosage",
            "severity": "moderate",
            "confidence_score": 0.77,
            "dose_recommendation": "Limit simvastatin to ≤40 mg/day; consider alternative statin.",
            "monitoring": "Routine CK monitoring; instruct patient to report muscle pain.",
            "rationale": "Partially reduced SLCO1B1 function increases plasma simvastatin exposure.",
        },
        "NM": {
            "risk_label": "Safe",
            "severity": "low",
            "confidence_score": 0.85,
            "dose_recommendation": "Standard dosing per label.",
            "monitoring": "Routine clinical monitoring.",
            "rationale": "Normal SLCO1B1 transport function; standard simvastatin clearance expected.",
        },
    },
    "TPMT": {
        "PM": {
            "risk_label": "Toxic",
            "severity": "critical",
            "confidence_score": 0.95,
            "dose_recommendation": "Reduce azathioprine to 10% of standard dose (or use alternative immunosuppressant).",
            "monitoring": "CBC weekly for first 4 weeks, then monthly.",
            "rationale": "TPMT-deficient patients accumulate thioguanine nucleotides, causing severe myelotoxicity.",
        },
        "IM": {
            "risk_label": "Adjust Dosage",
            "severity": "moderate",
            "confidence_score": 0.82,
            "dose_recommendation": "Reduce dose to 50–70% of standard; titrate based on tolerance.",
            "monitoring": "CBC bi-weekly for first 2 months.",
            "rationale": "Heterozygous TPMT deficiency increases TGN accumulation.",
        },
        "NM": {
            "risk_label": "Safe",
            "severity": "low",
            "confidence_score": 0.90,
            "dose_recommendation": "Standard dosing per label.",
            "monitoring": "Routine CBC monitoring.",
            "rationale": "Normal TPMT activity; standard azathioprine metabolism expected.",
        },
    },
    "DPYD": {
        "PM": {
            "risk_label": "Toxic",
            "severity": "critical",
            "confidence_score": 0.97,
            "dose_recommendation": "CONTRAINDICATED. Do not administer fluorouracil or capecitabine.",
            "monitoring": "If unavoidable, reduce dose by ≥85% with close toxicity monitoring.",
            "rationale": "Complete DPYD deficiency causes severe, life-threatening fluorouracil toxicity.",
        },
        "IM": {
            "risk_label": "Adjust Dosage",
            "severity": "moderate",
            "confidence_score": 0.78,
            "dose_recommendation": "Reduce 5-FU starting dose by 25–50%; titrate based on toxicity.",
            "monitoring": "Close monitoring of CBC, LFTs, and clinical toxicity.",
            "rationale": "Partial DPYD deficiency increases fluorouracil exposure.",
        },
        "NM": {
            "risk_label": "Safe",
            "severity": "none",
            "confidence_score": 0.88,
            "dose_recommendation": "Standard dosing per label.",
            "monitoring": "Routine toxicity monitoring.",
            "rationale": "Normal DPYD activity; standard fluorouracil metabolism expected.",
        },
    },
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _infer_alleles(variants: list[VariantInfo], gene: str) -> list[tuple[str, str]]:
    gene_rsids = STAR_ALLELE_RSIDS.get(gene, {})
    hits: list[tuple[str, str]] = []
    seen: set[str] = set()
    for v in variants:
        rsid = v.rsid
        if rsid and rsid in gene_rsids and rsid not in seen:
            star, activity = gene_rsids[rsid]
            hits.append((star, activity))
            seen.add(rsid)
    return hits


def _alleles_to_diplotype(allele_hits: list[tuple[str, str]], gene: str) -> tuple[str, str]:
    if not allele_hits:
        return "*1/*1", "normal+normal"
    activities = [act for (_, act) in allele_hits]
    stars = [star for (star, _) in allele_hits]
    if len(activities) == 1:
        return f"{stars[0]}/*1", f"{activities[0]}+normal"
    return f"{stars[0]}/{stars[1]}", f"{activities[0]}+{activities[1]}"


def _lookup_phenotype(gene: str, pair_key: str) -> str:
    gene_map = PHENOTYPE_MAP.get(gene, {})
    pheno = gene_map.get(pair_key)
    if pheno:
        return pheno
    reversed_key = "+".join(reversed(pair_key.split("+")))
    pheno = gene_map.get(reversed_key)
    if pheno:
        return pheno
    return gene_map.get("default", "NM")


def _lookup_risk(gene: str, phenotype_abbr: str) -> RiskRule:
    rule = RISK_RULES.get(gene, {}).get(phenotype_abbr)
    if rule:
        return rule
    return {
        "risk_label": "Unknown",
        "severity": "none",
        "confidence_score": 0.50,
        "dose_recommendation": "Consult current CPIC guidelines; no high-risk variant identified.",
        "monitoring": "Standard clinical monitoring.",
        "rationale": "Insufficient pharmacogenomic data to determine risk for this gene–drug pair.",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def assess_risk(
    drug: str,
    gene: str,
    detected_variants: list[VariantInfo],
) -> tuple[RiskAssessment, PharmacogenomicProfile, dict[str, Any]]:
    """
    Perform pharmacogenomic risk assessment.

    Returns:
        (RiskAssessment, PharmacogenomicProfile, clinical_recommendation dict)
    """
    drug_upper = drug.upper()
    gene_upper = gene.upper()

    logger.info("Risk assessment: drug=%s gene=%s variants=%d", drug_upper, gene_upper, len(detected_variants))

    allele_hits = _infer_alleles(detected_variants, gene_upper)
    diplotype, pair_key = _alleles_to_diplotype(allele_hits, gene_upper)
    logger.info("Diplotype: %s  pair_key: %s", diplotype, pair_key)

    phenotype_abbr = _lookup_phenotype(gene_upper, pair_key)
    phenotype_full = PHENOTYPE_FULL.get(phenotype_abbr, phenotype_abbr)
    logger.info("Phenotype: %s (%s)", phenotype_abbr, phenotype_full)

    rule = _lookup_risk(gene_upper, phenotype_abbr)

    risk_assessment = RiskAssessment(
        risk_label=rule["risk_label"],
        confidence_score=float(rule["confidence_score"]),
        severity=rule["severity"],
    )

    pgx_profile = PharmacogenomicProfile(
        primary_gene=gene_upper,
        diplotype=diplotype,
        phenotype=phenotype_abbr,
        detected_variants=detected_variants,
    )

    clinical_recommendation: dict[str, Any] = {
        "dose_recommendation": rule.get("dose_recommendation", ""),
        "monitoring": rule.get("monitoring", ""),
        "rationale": rule.get("rationale", ""),
        "drug": drug_upper,
        "gene": gene_upper,
        "phenotype": phenotype_abbr,
        "phenotype_full": phenotype_full,
    }

    return risk_assessment, pgx_profile, clinical_recommendation
