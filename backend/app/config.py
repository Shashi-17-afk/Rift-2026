"""
Application configuration.
Loads environment variables and defines constants for supported genes and drugs.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from backend root
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)

# OpenAI-compatible LLM settings
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_TIMEOUT_SECONDS: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "30"))

# Supported pharmacogenomic genes
SUPPORTED_GENES: frozenset[str] = frozenset({
    "CYP2D6",
    "CYP2C19",
    "CYP2C9",
    "SLCO1B1",
    "TPMT",
    "DPYD",
})

# Supported drugs and their primary gene
SUPPORTED_DRUGS: frozenset[str] = frozenset({
    "CODEINE",
    "WARFARIN",
    "CLOPIDOGREL",
    "SIMVASTATIN",
    "AZATHIOPRINE",
    "FLUOROURACIL",
})

# Drug -> Primary gene mapping
DRUG_TO_GENE: dict[str, str] = {
    "CODEINE": "CYP2D6",
    "WARFARIN": "CYP2C9",
    "CLOPIDOGREL": "CYP2C19",
    "SIMVASTATIN": "SLCO1B1",
    "AZATHIOPRINE": "TPMT",
    "FLUOROURACIL": "DPYD",
}

# Gene -> chromosome for coordinate-based filtering (hg19/GRCh37)
# Used when VCF lacks gene annotations
GENE_CHROMOSOME_MAP: dict[str, str] = {
    "CYP2D6": "22",
    "CYP2C19": "10",
    "CYP2C9": "10",
    "SLCO1B1": "12",
    "TPMT": "6",
    "DPYD": "1",
}

# VCF upload limits
MAX_VCF_SIZE_MB: int = int(os.getenv("MAX_VCF_SIZE_MB", "50"))
MAX_VCF_SIZE_BYTES: int = MAX_VCF_SIZE_MB * 1024 * 1024
ALLOWED_VCF_EXTENSIONS: tuple[str, ...] = (".vcf", ".vcf.gz", ".bcf")
