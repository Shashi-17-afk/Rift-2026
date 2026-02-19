"""
tests/test_vcf_parser.py
Unit tests for app.services.vcf_parser
"""
from __future__ import annotations

import textwrap

import pytest

from app.services.vcf_parser import ParseResult, parse_vcf_bytes, parse_vcf_path
from app.utils.exceptions import VCFParseError


# ── Helpers ───────────────────────────────────────────────────────────────

VALID_VCF = textwrap.dedent("""\
    ##fileformat=VCFv4.2
    ##INFO=<ID=DP,Number=1,Type=Integer,Description="Depth">
    ##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">
    #CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE
    10\t96741053\trs1799853\tC\tT\t99\tPASS\tDP=30\tGT\t0/1
    22\t42522613\trs3892097\tC\tT\t95\tPASS\tDP=28\tGT\t0/1
""").encode()

NO_VARIANT_VCF = textwrap.dedent("""\
    ##fileformat=VCFv4.2
    ##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">
    #CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE
""").encode()


# ── parse_vcf_bytes ───────────────────────────────────────────────────────

class TestParseVcfBytes:

    def test_returns_parse_result(self):
        result = parse_vcf_bytes(VALID_VCF)
        assert isinstance(result, ParseResult)

    def test_success_flag_true_on_valid_vcf(self):
        result = parse_vcf_bytes(VALID_VCF)
        assert result.success is True

    def test_variant_count_matches(self):
        result = parse_vcf_bytes(VALID_VCF)
        assert result.variant_count == 2
        assert len(result.variants) == 2

    def test_variant_has_required_fields(self):
        result = parse_vcf_bytes(VALID_VCF)
        v = result.variants[0]
        for field in ("CHROM", "POS", "ID", "REF", "ALT", "INFO", "samples"):
            assert field in v, f"Missing field: {field}"

    def test_rsid_extracted(self):
        result = parse_vcf_bytes(VALID_VCF)
        ids = [v["ID"] for v in result.variants]
        assert "rs1799853" in ids
        assert "rs3892097" in ids

    def test_chrom_is_string(self):
        result = parse_vcf_bytes(VALID_VCF)
        for v in result.variants:
            assert isinstance(v["CHROM"], str)

    def test_pos_is_int(self):
        result = parse_vcf_bytes(VALID_VCF)
        for v in result.variants:
            assert isinstance(v["POS"], int)

    def test_alt_is_list(self):
        result = parse_vcf_bytes(VALID_VCF)
        for v in result.variants:
            assert isinstance(v["ALT"], list)

    def test_vcf_with_no_variants(self):
        result = parse_vcf_bytes(NO_VARIANT_VCF)
        assert result.success is True
        assert result.variant_count == 0
        assert result.variants == []

    def test_empty_bytes_raises(self):
        with pytest.raises(VCFParseError):
            parse_vcf_bytes(b"")

    def test_malformed_vcf_raises(self):
        with pytest.raises(VCFParseError):
            parse_vcf_bytes(b"NOT A VCF FILE AT ALL\nRANDOM GARBAGE\n")

    def test_sample_vcf_parses_7_variants(self, sample_vcf_path):
        data = sample_vcf_path.read_bytes()
        result = parse_vcf_bytes(data)
        assert result.success is True
        assert result.variant_count == 7

    def test_samples_list_populated(self):
        result = parse_vcf_bytes(VALID_VCF)
        for v in result.variants:
            assert isinstance(v["samples"], list)
            assert len(v["samples"]) >= 1
            assert "sample" in v["samples"][0]


# ── parse_vcf_path ────────────────────────────────────────────────────────

class TestParseVcfPath:

    def test_parses_sample_file(self, sample_vcf_path):
        result = parse_vcf_path(str(sample_vcf_path))
        assert result.success is True
        assert result.variant_count > 0

    def test_nonexistent_path_raises(self):
        with pytest.raises(VCFParseError, match="not found"):
            parse_vcf_path("/nonexistent/path/does_not_exist.vcf")
