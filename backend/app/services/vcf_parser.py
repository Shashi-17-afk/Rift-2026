"""
vcf_parser.py — VCF file parsing service.

Accepts raw VCF bytes or a temp-file path.
Uses PyVCF3 to parse records into plain dicts.
Raises VCFParseError for any malformed / unreadable VCF.
"""

from __future__ import annotations

import io
import logging
import tempfile
from pathlib import Path
from typing import Any
import cyvcf2 as vcf  # PyVCF3

from app.utils.exceptions import VCFParseError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public data structure
# ---------------------------------------------------------------------------

class ParseResult:
    """Container returned by parse_vcf_bytes / parse_vcf_path."""

    __slots__ = ("variants", "success", "variant_count", "error_message")

    def __init__(
        self,
        variants: list[dict[str, Any]],
        success: bool,
        variant_count: int,
        error_message: str = "",
    ) -> None:
        self.variants = variants
        self.success = success
        self.variant_count = variant_count
        self.error_message = error_message


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _record_to_dict(record: vcf.Variant) -> dict[str, Any]:
    """Convert a PyVCF3 Record to a serialisable dict."""
    # ALT alleles may be symbolic (e.g. <DEL>) – convert to strings safely
    alts: list[str] = []
    if record.ALT:
        for a in record.ALT:
            alts.append(str(a) if a is not None else ".")

    # INFO: flatten to plain Python types (some values are lists)
    info: dict[str, Any] = {}
    for key, val in (record.INFO or {}).items():
        if isinstance(val, list):
            info[key] = [str(v) for v in val]
        elif val is None:
            info[key] = None
        else:
            info[key] = val

    # Sample genotypes (if present)
    samples: list[dict[str, Any]] = []
    for sample in record.samples:
        gt_data: dict[str, Any] = {"sample": sample.sample}
        try:
            gt_data["GT"] = sample["GT"]
        except (AttributeError, KeyError):
            gt_data["GT"] = None
        samples.append(gt_data)

    return {
        "CHROM": str(record.CHROM),
        "POS": int(record.POS),
        "ID": record.ID or ".",          # rsID when available
        "REF": str(record.REF),
        "ALT": alts,
        "QUAL": record.QUAL,
        "FILTER": [str(f) for f in record.FILTER] if record.FILTER else [],
        "INFO": info,
        "FORMAT": record.FORMAT or "",
        "samples": samples,
    }

def _parse_reader(reader: vcf.VCF) -> list[dict[str, Any]]:
    """Iterate through all records and return list of dicts."""
    variants: list[dict[str, Any]] = []
    for record in reader:
        try:
            variants.append(_record_to_dict(record))
        except Exception as exc:  
            # Log but continue — one bad record shouldn't abort everything
            logger.warning("Skipping malformed VCF record: %s", exc)
    return variants

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_vcf_bytes(vcf_bytes: bytes) -> ParseResult:
    """
    Parse a VCF file from raw bytes.

    Args:
        vcf_bytes: Raw bytes of the VCF file (plain or gzip-compressed).

    Returns:
        ParseResult with variant list and success flag.

    Raises:
        VCFParseError: If the content is not a valid VCF.
    """
    if not vcf_bytes:
        raise VCFParseError("Uploaded VCF file is empty.")

    # Write to a temp file so PyVCF3 can seek freely (needed for tabix / gz)
    suffix = ".vcf.gz" if vcf_bytes[:2] == b"\x1f\x8b" else ".vcf"
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(vcf_bytes)
            tmp_path = tmp.name
        return parse_vcf_path(tmp_path)
    except VCFParseError:
        raise
    except Exception as exc:
        logger.error("Unexpected error writing temp VCF: %s", exc)
        raise VCFParseError(f"Could not process VCF file: {exc}") from exc
    finally:
        # Clean up temp file
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:  
            pass

def parse_vcf_path(file_path: str) -> ParseResult:
    """
    Parse a VCF file from a filesystem path.

    Args:
        file_path: Absolute or relative path to a .vcf / .vcf.gz file.

    Returns:
        ParseResult with variant list and success flag.

    Raises:
        VCFParseError: If the file cannot be opened or parsed.
    """
    path = Path(file_path)
    if not path.exists():
        raise VCFParseError(f"VCF file not found: {file_path}")

    try:
        reader = vcf.VCF(str(path))
        variants = _parse_reader(reader)
    except vcf.VCFError as exc:
        logger.warning("VCF parse error: %s", exc)
        raise VCFParseError(f"Malformed VCF: {exc}") from exc
    except Exception as exc:
        logger.error("Unexpected VCF parse failure: %s", exc)
        raise VCFParseError(f"Failed to parse VCF: {exc}") from exc

    logger.info("Parsed %d variants from %s", len(variants), path.name)
    return ParseResult(
        variants=variants,
        success=True,
        variant_count=len(variants),
    )
