"""
variant_extractor.py — Pharmacogenomic variant extraction service.

Filters parsed VCF variants to those relevant to a target gene.
Supports two strategies:
  1. Annotation-based: looks for gene name in INFO/ANN or INFO/CSQ fields.
  2. Coordinate-based fallback: uses chromosome + position windows from
     GENE_REGION_MAP (hg19/GRCh37 coordinates).

Returns a list of VariantInfo models ready for the risk engine.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import GENE_CHROMOSOME_MAP
from app.models.schemas import VariantInfo
from app.utils.exceptions import GeneNotFoundError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Genomic coordinate windows (hg19/GRCh37) for coordinate-based fallback.
# Format: gene -> (chromosome, start_bp, end_bp)
# ---------------------------------------------------------------------------

GENE_REGION_MAP: dict[str, tuple[str, int, int]] = {
    "CYP2D6":  ("22", 42_522_500,  42_526_883),
    "CYP2C19": ("10", 96_522_463,  96_612_671),
    "CYP2C9":  ("10", 96_698_415,  96_749_148),
    "SLCO1B1": ("12", 21_281_254,  21_430_918),
    "TPMT":    ("6",  18_128_556,  18_155_418),
    "DPYD":    ("1",  97_541_298,  98_388_615),
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_rsid(record: dict[str, Any]) -> str | None:
    """Return rsID string if present and looks like rs<digits>."""
    raw = record.get("ID", ".")
    if raw and isinstance(raw, str) and raw.startswith("rs"):
        return raw
    return None


def _annotation_gene_match(record: dict[str, Any], gene: str) -> bool:
    """
    Return True if any VEP/SnpEff annotation field names this gene.
    Checks INFO keys: ANN, CSQ, GENEINFO, Gene.
    """
    info: dict[str, Any] = record.get("INFO", {})

    # VEP CSQ field: "Allele|Consequence|IMPACT|SYMBOL|Gene|..."
    csq_raw = info.get("CSQ")
    if csq_raw:
        entries = csq_raw if isinstance(csq_raw, list) else [csq_raw]
        for entry in entries:
            parts = str(entry).split("|")
            # SYMBOL is typically at index 3, Gene Ensembl ID at 4
            for part in parts[:8]:
                if part.upper() == gene.upper():
                    return True

    # SnpEff ANN field: "Allele|Effect|Impact|GeneName|GeneID|..."
    ann_raw = info.get("ANN")
    if ann_raw:
        entries = ann_raw if isinstance(ann_raw, list) else [ann_raw]
        for entry in entries:
            parts = str(entry).split("|")
            for part in parts[:5]:
                if part.upper() == gene.upper():
                    return True

    # Simple GENEINFO key (used in ClinVar/dbSNP VCFs)
    geneinfo = info.get("GENEINFO", "")
    if geneinfo and gene.upper() in str(geneinfo).upper():
        return True

    # Explicit "Gene" INFO field
    gene_field = info.get("Gene", "")
    if gene_field and gene.upper() in str(gene_field).upper():
        return True

    return False


def _coordinate_match(record: dict[str, Any], gene: str) -> bool:
    """
    Return True if the record's chromosome and position fall within
    the known genomic window for this gene.
    """
    region = GENE_REGION_MAP.get(gene)
    if not region:
        return False
    chrom, start, end = region

    # Normalise chromosome: strip 'chr' prefix
    rec_chrom = str(record.get("CHROM", "")).lstrip("chr")
    if rec_chrom != chrom:
        return False

    pos = int(record.get("POS", 0))
    return start <= pos <= end


def _record_to_variant_info(record: dict[str, Any], gene: str) -> list[VariantInfo]:
    """
    Convert a raw VCF record dict to one VariantInfo per ALT allele.
    """
    alts: list[str] = record.get("ALT", ["."])
    if not alts:
        alts = ["."]

    rsid = _extract_rsid(record)
    chrom = str(record.get("CHROM", "")).lstrip("chr")
    pos = int(record.get("POS", 0))
    ref = str(record.get("REF", ""))

    return [
        VariantInfo(
            gene=gene,
            chromosome=chrom,
            position=pos,
            ref=ref,
            alt=alt,
            rsid=rsid,
        )
        for alt in alts
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_variants(
    variants: list[dict[str, Any]],
    gene: str,
    *,
    force_coordinate_fallback: bool = False,
) -> list[VariantInfo]:
    """
    Filter parsed VCF variants to those relevant to *gene*.

    Strategy:
    - First tries annotation-based matching (CSQ/ANN/GENEINFO fields).
    - If no annotation hits are found, falls back to coordinate-based
      filtering using GENE_REGION_MAP.

    Args:
        variants: List of raw variant dicts from vcf_parser.
        gene: Gene name (e.g. "CYP2D6"). Must be in GENE_REGION_MAP.
        force_coordinate_fallback: Skip annotation check entirely.

    Returns:
        List of VariantInfo instances for the specified gene.

    Raises:
        GeneNotFoundError: If gene is not in the known region map.
    """
    gene_upper = gene.upper()

    if gene_upper not in GENE_REGION_MAP:
        raise GeneNotFoundError(gene)

    matched: list[VariantInfo] = []

    if not force_coordinate_fallback:
        # --- Strategy 1: annotation-based ---
        annotation_hits: list[dict[str, Any]] = [
            r for r in variants if _annotation_gene_match(r, gene_upper)
        ]
        if annotation_hits:
            logger.info(
                "Gene %s: %d annotation-matched variants", gene_upper, len(annotation_hits)
            )
            for record in annotation_hits:
                matched.extend(_record_to_variant_info(record, gene_upper))
            return matched

    # --- Strategy 2: coordinate-based fallback ---
    logger.info(
        "Gene %s: no annotation hits — using coordinate-based filtering", gene_upper
    )
    coord_hits: list[dict[str, Any]] = [
        r for r in variants if _coordinate_match(r, gene_upper)
    ]
    logger.info(
        "Gene %s: %d coordinate-matched variants", gene_upper, len(coord_hits)
    )
    for record in coord_hits:
        matched.extend(_record_to_variant_info(record, gene_upper))

    return matched
