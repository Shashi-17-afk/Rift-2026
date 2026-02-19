# tests/conftest.py
"""
Shared pytest fixtures for PharmaGuard test suite.
Provides: vcf_bytes, parsed_variants, sample_vcf_path, async http test client.
"""
from __future__ import annotations

import io
import os
import sys
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Ensure the backend root is on sys.path so imports resolve
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── Minimal valid VCF content ──────────────────────────────────────────────
MINIMAL_VCF: bytes = textwrap.dedent("""\
    ##fileformat=VCFv4.2
    ##INFO=<ID=DP,Number=1,Type=Integer,Description="Depth">
    ##INFO=<ID=Gene,Number=1,Type=String,Description="Gene">
    ##INFO=<ID=GENEINFO,Number=1,Type=String,Description="Gene info">
    ##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">
    #CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE
    10\t96741053\trs1799853\tC\tT\t99\tPASS\tDP=45;Gene=CYP2C9;GENEINFO=CYP2C9\tGT\t0/1
    10\t96740980\trs1057910\tA\tC\t98\tPASS\tDP=52;Gene=CYP2C9;GENEINFO=CYP2C9\tGT\t0/1
    22\t42522613\trs3892097\tC\tT\t95\tPASS\tDP=38;Gene=CYP2D6;GENEINFO=CYP2D6\tGT\t0/1
    10\t96522463\trs4244285\tG\tA\t97\tPASS\tDP=60;Gene=CYP2C19;GENEINFO=CYP2C19\tGT\t0/1
    12\t21331549\trs4149056\tT\tC\t96\tPASS\tDP=44;Gene=SLCO1B1;GENEINFO=SLCO1B1\tGT\t0/1
    6\t18155418\trs1800460\tC\tT\t94\tPASS\tDP=50;Gene=TPMT;GENEINFO=TPMT\tGT\t0/1
    1\t97915614\trs3918290\tC\tT\t99\tPASS\tDP=55;Gene=DPYD;GENEINFO=DPYD\tGT\t0/1
""").encode()

EMPTY_VCF: bytes = b""          # truly empty
MALFORMED_VCF: bytes = b"THIS IS NOT A VCF FILE AT ALL"


@pytest.fixture(scope="session")
def sample_vcf_path() -> Path:
    """Path to the sample.vcf test file on disk."""
    p = Path(__file__).parent / "sample.vcf"
    assert p.exists(), f"sample.vcf not found at {p}"
    return p


@pytest.fixture(scope="session")
def vcf_bytes() -> bytes:
    """Minimal valid VCF as bytes (uses in-memory content, no disk read)."""
    return MINIMAL_VCF  # already bytes


@pytest.fixture(scope="session")
def parsed_variants(vcf_bytes):
    """Pre-parsed variants from the minimal VCF (session-scoped for speed)."""
    from app.services.vcf_parser import parse_vcf_bytes
    result = parse_vcf_bytes(vcf_bytes)
    return result.variants


@pytest.fixture(scope="session")
def api_client():
    """FastAPI TestClient (no running server needed)."""
    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
