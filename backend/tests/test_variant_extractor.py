"""
tests/test_variant_extractor.py
Unit tests for app.services.variant_extractor
"""
from __future__ import annotations

import pytest

from app.models.schemas import VariantInfo
from app.services.variant_extractor import (
    GENE_REGION_MAP,
    extract_variants,
    _annotation_gene_match,
    _coordinate_match,
)
from app.utils.exceptions import GeneNotFoundError


# ── Fixture: raw variant dicts (same shape as vcf_parser output) ──────────

def _make_variant(chrom, pos, rsid=".", ref="C", alt="T",
                   gene_info=None, geneinfo=None, ann=None, csq=None):
    info = {}
    if gene_info is not None:
        info["Gene"] = gene_info
    if geneinfo is not None:
        info["GENEINFO"] = geneinfo
    if ann is not None:
        info["ANN"] = ann
    if csq is not None:
        info["CSQ"] = csq
    return {
        "CHROM": str(chrom),
        "POS": pos,
        "ID": rsid,
        "REF": ref,
        "ALT": [alt],
        "INFO": info,
        "samples": [],
    }


CYP2C9_LIT_VARIANT = _make_variant("10", 96741053, "rs1799853", gene_info="CYP2C9")
CYP2D6_LIT_VARIANT = _make_variant("22", 42522613, "rs3892097", gene_info="CYP2D6")
NO_ANNO_CYP2C9     = _make_variant("10", 96741053)    # no annotation, but inside window
OUTSIDE_WINDOW     = _make_variant("10", 1000)        # chr10 but well outside any gene window
WRONG_CHROM        = _make_variant("9",  96741053)    # right pos, wrong chr


# ── _annotation_gene_match ────────────────────────────────────────────────

class TestAnnotationGeneMatch:

    def test_gene_info_field_matches(self):
        v = _make_variant("10", 100, gene_info="CYP2C9")
        assert _annotation_gene_match(v, "CYP2C9") is True

    def test_geneinfo_field_matches(self):
        v = _make_variant("10", 100, geneinfo="CYP2C9")
        assert _annotation_gene_match(v, "CYP2C9") is True

    def test_ann_field_matches(self):
        # SnpEff ANN: "T|missense_variant|MODERATE|CYP2C9|..."
        v = _make_variant("10", 100, ann=["T|missense|MODERATE|CYP2C9|ENSG123|..."])
        assert _annotation_gene_match(v, "CYP2C9") is True

    def test_csq_field_matches(self):
        # VEP CSQ: "T|missense_variant|MODERATE|CYP2C9|..."
        v = _make_variant("10", 100, csq=["T|missense|MODERATE|CYP2C9|..."])
        assert _annotation_gene_match(v, "CYP2C9") is True

    def test_wrong_gene_no_match(self):
        v = _make_variant("10", 100, gene_info="CYP2C9")
        assert _annotation_gene_match(v, "CYP2D6") is False

    def test_case_insensitive(self):
        v = _make_variant("10", 100, gene_info="cyp2c9")
        assert _annotation_gene_match(v, "CYP2C9") is True

    def test_no_annotation_returns_false(self):
        v = _make_variant("10", 100)   # empty INFO
        assert _annotation_gene_match(v, "CYP2C9") is False


# ── _coordinate_match ─────────────────────────────────────────────────────

class TestCoordinateMatch:

    @pytest.mark.parametrize("gene,chrom,pos,expected", [
        ("CYP2C9",  "10", 96741053, True),   # inside window
        ("CYP2C9",  "10", 96698415, True),   # at start of window
        ("CYP2C9",  "10", 96749148, True),   # at end of window
        ("CYP2C9",  "10", 96698000, False),  # just before window
        ("CYP2C9",  "10", 96750000, False),  # just after window
        ("CYP2D6",  "22", 42522613, True),
        ("SLCO1B1", "12", 21331549, True),
        ("TPMT",    "6",  18155418, True),
        ("DPYD",    "1",  97915614, True),
        ("CYP2C9",  "9",  96741053, False),  # wrong chromosome
    ])
    def test_coordinate_matching(self, gene, chrom, pos, expected):
        v = _make_variant(chrom, pos)
        assert _coordinate_match(v, gene) is expected

    def test_chr_prefix_stripped(self):
        v = _make_variant("chr10", 96741053)   # VCF has "chr" prefix
        assert _coordinate_match(v, "CYP2C9") is True


# ── extract_variants ──────────────────────────────────────────────────────

class TestExtractVariants:

    def test_returns_list_of_variant_info(self, parsed_variants):
        result = extract_variants(parsed_variants, "CYP2C9")
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, VariantInfo)

    def test_annotation_match_finds_cyp2c9(self, parsed_variants):
        result = extract_variants(parsed_variants, "CYP2C9")
        assert len(result) >= 1
        assert all(v.gene == "CYP2C9" for v in result)

    def test_annotation_match_finds_cyp2d6(self, parsed_variants):
        result = extract_variants(parsed_variants, "CYP2D6")
        assert len(result) >= 1
        assert all(v.gene == "CYP2D6" for v in result)

    def test_rsid_preserved(self, parsed_variants):
        result = extract_variants(parsed_variants, "CYP2C9")
        rsids = [v.rsid for v in result]
        assert "rs1799853" in rsids

    def test_chromosome_set(self, parsed_variants):
        result = extract_variants(parsed_variants, "CYP2C9")
        for v in result:
            assert v.chromosome == "10"

    def test_position_set(self, parsed_variants):
        result = extract_variants(parsed_variants, "CYP2C9")
        positions = [v.position for v in result]
        assert 96741053 in positions

    def test_all_six_genes_find_variants(self, parsed_variants):
        genes = ["CYP2C9", "CYP2D6", "CYP2C19", "SLCO1B1", "TPMT", "DPYD"]
        for gene in genes:
            result = extract_variants(parsed_variants, gene)
            assert len(result) >= 1, f"No variants found for {gene}"

    def test_unknown_gene_raises(self, parsed_variants):
        with pytest.raises(GeneNotFoundError):
            extract_variants(parsed_variants, "UNKNOWN_GENE")

    def test_coordinate_fallback_when_no_annotations(self):
        """When no annotation fields present, coord fallback should still find CYP2C9."""
        unannotated = [
            _make_variant("10", 96741053, rsid="rs1799853"),  # no gene annotation
        ]
        result = extract_variants(unannotated, "CYP2C9", force_coordinate_fallback=True)
        assert len(result) >= 1

    def test_empty_variants_list_returns_empty(self):
        result = extract_variants([], "CYP2C9")
        assert result == []

    def test_unrelated_variants_excluded(self):
        """Variants on unrelated chromosomes/positions should be excluded."""
        unrelated = [_make_variant("1", 999999, gene_info="BRCA1")]
        result = extract_variants(unrelated, "CYP2C9")
        assert result == []

    def test_ref_and_alt_populated(self, parsed_variants):
        result = extract_variants(parsed_variants, "CYP2C9")
        for v in result:
            assert v.ref != ""
            assert v.alt != ""
