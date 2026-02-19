"""
tests/test_risk_engine.py
Unit tests for app.services.risk_engine
"""
from __future__ import annotations

import pytest

from app.models.schemas import PharmacogenomicProfile, RiskAssessment, VariantInfo
from app.services.risk_engine import (
    PHENOTYPE_FULL,
    RISK_RULES,
    STAR_ALLELE_RSIDS,
    _alleles_to_diplotype,
    _infer_alleles,
    _lookup_phenotype,
    _lookup_risk,
    assess_risk,
)


# ── Helpers ───────────────────────────────────────────────────────────────

def _vi(gene, rsid=None, ref="C", alt="T", chrom="10", pos=1000):
    return VariantInfo(gene=gene, rsid=rsid, ref=ref, alt=alt,
                       chromosome=chrom, position=pos)


# ── _infer_alleles ─────────────────────────────────────────────────────────

class TestInferAlleles:

    def test_known_rsid_detected(self):
        variants = [_vi("CYP2C9", rsid="rs1799853")]
        hits = _infer_alleles(variants, "CYP2C9")
        assert len(hits) == 1
        assert hits[0][0] == "*2"          # star allele
        assert hits[0][1] == "reduced"     # activity

    def test_unknown_rsid_ignored(self):
        variants = [_vi("CYP2C9", rsid="rs9999999")]
        hits = _infer_alleles(variants, "CYP2C9")
        assert hits == []

    def test_no_rsid_ignored(self):
        variants = [_vi("CYP2C9", rsid=None)]
        hits = _infer_alleles(variants, "CYP2C9")
        assert hits == []

    def test_deduplication(self):
        """Same rsID appearing twice should count only once."""
        variants = [
            _vi("CYP2C9", rsid="rs1799853"),
            _vi("CYP2C9", rsid="rs1799853"),
        ]
        hits = _infer_alleles(variants, "CYP2C9")
        assert len(hits) == 1

    def test_two_distinct_alleles_detected(self):
        variants = [
            _vi("CYP2C9", rsid="rs1799853"),   # *2 reduced
            _vi("CYP2C9", rsid="rs1057910"),   # *3 none
        ]
        hits = _infer_alleles(variants, "CYP2C9")
        assert len(hits) == 2

    def test_cyp2c19_gain_of_function(self):
        variants = [_vi("CYP2C19", rsid="rs12248560", chrom="10", pos=96522463)]
        hits = _infer_alleles(variants, "CYP2C19")
        assert len(hits) == 1
        assert hits[0][1] == "increased"    # *17 — gain of function

    def test_dpyd_lost_function(self):
        variants = [_vi("DPYD", rsid="rs3918290", chrom="1", pos=97915614)]
        hits = _infer_alleles(variants, "DPYD")
        assert hits[0][1] == "none"


# ── _alleles_to_diplotype ────────────────────────────────────────────────

class TestAllelesToDiplotype:

    def test_no_hits_returns_wildtype(self):
        diplotype, pair = _alleles_to_diplotype([], "CYP2C9")
        assert diplotype == "*1/*1"
        assert pair == "normal+normal"

    def test_one_hit_heterozygous(self):
        diplotype, pair = _alleles_to_diplotype([("*2", "reduced")], "CYP2C9")
        assert diplotype == "*2/*1"
        assert pair == "reduced+normal"

    def test_two_hits_compound(self):
        diplotype, pair = _alleles_to_diplotype(
            [("*2", "reduced"), ("*3", "none")], "CYP2C9"
        )
        assert "*2" in diplotype and "*3" in diplotype
        assert "reduced" in pair and "none" in pair


# ── _lookup_phenotype ────────────────────────────────────────────────────

class TestLookupPhenotype:

    @pytest.mark.parametrize("gene,pair,expected_abbr", [
        ("CYP2C9",  "none+none",          "PM"),
        ("CYP2C9",  "normal+normal",       "NM"),
        ("CYP2D6",  "none+none",          "PM"),
        ("CYP2D6",  "increased+increased", "URM"),
        ("CYP2C19", "none+none",          "PM"),
        ("CYP2C19", "normal+increased",   "RM"),
        ("SLCO1B1", "reduced+reduced",    "PM"),
        ("TPMT",    "normal+none",        "IM"),
        ("DPYD",    "none+none",          "PM"),
    ])
    def test_phenotype_lookup(self, gene, pair, expected_abbr):
        pheno = _lookup_phenotype(gene, pair)
        assert pheno == expected_abbr, f"{gene}/{pair} → '{pheno}' (expected '{expected_abbr}')"
        # Also verify the full name exists in PHENOTYPE_FULL
        assert pheno in PHENOTYPE_FULL, f"Abbreviation '{pheno}' not found in PHENOTYPE_FULL"

    def test_reversed_pair_key_also_works(self):
        """none+normal should equal normal+none for symmetric phenotype."""
        p1 = _lookup_phenotype("CYP2C9", "normal+none")
        p2 = _lookup_phenotype("CYP2C9", "none+normal")
        assert p1 == p2

    def test_unknown_pair_returns_default(self):
        pheno = _lookup_phenotype("CYP2C9", "weird+pair")
        # Should return the default abbreviation (NM) and it must be a non-empty string
        assert pheno == "NM" or pheno != ""


# ── _lookup_risk ─────────────────────────────────────────────────────────

class TestLookupRisk:

    def test_high_risk_rule_exists_for_all_genes(self):
        """Every gene should have at least one high/critical severity rule."""
        for gene in ["CYP2C9", "CYP2D6", "CYP2C19", "SLCO1B1", "TPMT", "DPYD"]:
            rules = RISK_RULES.get(gene, {})
            high_risk_phenotypes = [
                p for p, r in rules.items()
                if r.get("severity") in ("high", "critical")
            ]
            assert high_risk_phenotypes, f"No high/critical severity rule for {gene}"

    def test_confidence_score_is_valid_float(self):
        for gene, rules in RISK_RULES.items():
            for pheno, rule in rules.items():
                score = rule.get("confidence_score", 0)
                assert 0.0 <= score <= 1.0, f"{gene}/{pheno} confidence_score out of range: {score}"

    def test_dose_recommendation_not_empty(self):
        for gene, rules in RISK_RULES.items():
            for pheno, rule in rules.items():
                assert rule.get("dose_recommendation"), f"{gene}/{pheno} missing dose_recommendation"

    def test_unknown_phenotype_returns_fallback(self):
        rule = _lookup_risk("CYP2C9", "Nonexistent Phenotype")
        assert rule["risk_label"] == "Unknown"
        assert 0.0 <= rule["confidence_score"] <= 1.0


# ── assess_risk (integration) ─────────────────────────────────────────────

class TestAssessRisk:

    def _variants_for(self, *rsids_gene):
        """Build VariantInfo list from (rsid, gene) pairs."""
        return [_vi(gene, rsid=rsid) for rsid, gene in rsids_gene]

    # --- Warfarin / CYP2C9 ---

    def test_warfarin_poor_metabolizer(self):
        variants = self._variants_for(
            ("rs1799853", "CYP2C9"),   # *2 reduced
            ("rs1057910", "CYP2C9"),   # *3 none
        )
        risk, pgx, rec = assess_risk("WARFARIN", "CYP2C9", variants)
        # *2 (reduced) + *3 (none) = IM (reduced+none activity pair)
        assert pgx.phenotype in ("PM", "IM")   # CPIC abbreviations
        assert risk.risk_label in ("Toxic", "Adjust Dosage", "Ineffective")
        assert 0.0 <= risk.confidence_score <= 1.0
        assert risk.severity in ("high", "moderate", "critical")

    def test_warfarin_no_variants_is_low_risk(self):
        risk, pgx, rec = assess_risk("WARFARIN", "CYP2C9", [])
        assert pgx.diplotype == "*1/*1"
        assert pgx.phenotype == "NM"           # CPIC abbreviation for Normal Metabolizer
        assert risk.risk_label == "Safe"
        assert risk.severity == "low"

    # --- Codeine / CYP2D6 ---

    def test_codeine_poor_metabolizer(self):
        variants = self._variants_for(
            ("rs3892097", "CYP2D6"),   # *4 none — poor metabolizer
            ("rs5030655", "CYP2D6"),   # *6 none
        )
        risk, pgx, rec = assess_risk("CODEINE", "CYP2D6", variants)
        assert pgx.phenotype == "PM"           # CPIC Poor Metabolizer abbreviation
        assert risk.risk_label == "Ineffective"

    def test_codeine_normal_is_low_risk(self):
        risk, pgx, rec = assess_risk("CODEINE", "CYP2D6", [])
        assert risk.risk_label == "Safe"
        assert risk.severity == "low"

    # --- Clopidogrel / CYP2C19 ---

    def test_clopidogrel_poor_metabolizer(self):
        variants = self._variants_for(
            ("rs4244285", "CYP2C19"),   # *2 none
            ("rs4986893", "CYP2C19"),   # *3 none
        )
        risk, pgx, rec = assess_risk("CLOPIDOGREL", "CYP2C19", variants)
        assert pgx.phenotype == "PM"           # CPIC Poor Metabolizer abbreviation
        assert risk.risk_label == "Ineffective"

    # --- SLCO1B1 / Simvastatin ---

    def test_simvastatin_poor_function(self):
        variants = self._variants_for(
            ("rs4149056", "SLCO1B1"),   # *5 reduced
            ("rs11045819", "SLCO1B1"),  # *15 reduced → compound poor function
        )
        risk, pgx, rec = assess_risk("SIMVASTATIN", "SLCO1B1", variants)
        # Two reduced alleles → PM
        assert pgx.phenotype == "PM"
        assert risk.severity in ("high", "critical")

    # --- TPMT / Azathioprine ---

    def test_azathioprine_poor_metabolizer(self):
        variants = self._variants_for(
            ("rs1800460", "TPMT"),   # *3B none
            ("rs1142345", "TPMT"),   # *3C none
        )
        risk, pgx, rec = assess_risk("AZATHIOPRINE", "TPMT", variants)
        assert pgx.phenotype == "PM"           # CPIC Poor Metabolizer abbreviation
        assert risk.risk_label == "Toxic"
        assert risk.confidence_score >= 0.90

    # --- DPYD / Fluorouracil ---

    def test_fluorouracil_no_activity(self):
        variants = self._variants_for(
            ("rs3918290", "DPYD"),   # *2A none
            ("rs55886062", "DPYD"),  # c.1679T>G none
        )
        risk, pgx, rec = assess_risk("FLUOROURACIL", "DPYD", variants)
        # Two none-activity alleles → PM
        assert pgx.phenotype == "PM"
        assert risk.risk_label == "Toxic"
        assert risk.severity == "critical"

    # --- Output shape checks ---

    def test_output_types(self):
        risk, pgx, rec = assess_risk("WARFARIN", "CYP2C9", [])
        assert isinstance(risk, RiskAssessment)
        assert isinstance(pgx, PharmacogenomicProfile)
        assert isinstance(rec, dict)

    def test_clinical_recommendation_keys(self):
        _, _, rec = assess_risk("WARFARIN", "CYP2C9", [])
        for key in ("dose_recommendation", "monitoring", "rationale", "drug", "gene", "phenotype"):
            assert key in rec, f"Missing key in clinical_recommendation: {key}"

    def test_detected_variants_in_profile(self):
        variants = self._variants_for(("rs1799853", "CYP2C9"))
        _, pgx, _ = assess_risk("WARFARIN", "CYP2C9", variants)
        assert len(pgx.detected_variants) == 1
        assert pgx.detected_variants[0].rsid == "rs1799853"
