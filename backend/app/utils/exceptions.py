"""
Custom exceptions for PharmaGuard.
Used for domain-specific errors; mapped to HTTP responses via FastAPI exception handlers.
"""

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


# --- Custom exception base ---


class PharmaGuardError(Exception):
    """Base exception for PharmaGuard domain errors."""

    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


# --- Domain exceptions ---


class VCFParseError(PharmaGuardError):
    """Raised when VCF file parsing fails (malformed, invalid format, etc.)."""

    def __init__(self, message: str = "Failed to parse VCF file"):
        super().__init__(message=message, status_code=422)


class GeneNotFoundError(PharmaGuardError):
    """Raised when a requested gene is not in the supported list."""

    def __init__(self, gene: str):
        super().__init__(
            message=f"Gene '{gene}' is not supported",
            status_code=400,
        )


class DrugNotSupportedError(PharmaGuardError):
    """Raised when a requested drug is not in the supported list."""

    def __init__(self, drug: str):
        super().__init__(
            message=f"Drug '{drug}' is not supported",
            status_code=400,
        )


class LLMServiceError(PharmaGuardError):
    """Raised when LLM/explanation service fails (API error, timeout, etc.)."""

    def __init__(self, message: str = "Explanation service unavailable"):
        super().__init__(message=message, status_code=503)


class FileValidationError(PharmaGuardError):
    """Raised when uploaded file fails validation (type, size, etc.)."""

    def __init__(self, message: str):
        super().__init__(message=message, status_code=400)


# --- FastAPI exception handlers ---


def register_exception_handlers(app):
    """
    Register custom exception handlers on the FastAPI app.
    Call this from main.py after creating the app.
    PharmaGuardError base handler catches all subclasses (VCFParseError, etc.).
    """

    @app.exception_handler(PharmaGuardError)
    async def pharma_guard_error_handler(request: Request, exc: PharmaGuardError):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.message,
                "error_type": exc.__class__.__name__,
            },
        )
