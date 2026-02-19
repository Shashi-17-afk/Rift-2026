"""
tests/test_api.py
Integration tests for the FastAPI endpoints using TestClient (no server needed).
"""
from __future__ import annotations

import io
import json
import textwrap

import pytest

from tests.conftest import MINIMAL_VCF, MALFORMED_VCF


# ── Helpers ───────────────────────────────────────────────────────────────

def _vcf_file(content: bytes = MINIMAL_VCF, filename: str = "test.vcf"):
    """Build a tuple for multipart file upload."""
    return ("file", (filename, io.BytesIO(content), "text/plain"))


def _post_analyze(client, patient_id="P001", drug="WARFARIN",
                  vcf_content=MINIMAL_VCF, filename="test.vcf"):
    return client.post(
        "/api/analyze",
        data={"patient_id": patient_id, "drug": drug},
        files=[_vcf_file(vcf_content, filename)],
    )


# ══════════════════════════════════════════════════════════════════════════
# GET /health
# ══════════════════════════════════════════════════════════════════════════

class TestHealthEndpoint:

    def test_returns_200(self, api_client):
        resp = api_client.get("/health")
        assert resp.status_code == 200

    def test_status_is_healthy(self, api_client):
        data = api_client.get("/health").json()
        assert data["status"] == "healthy"

    def test_version_present(self, api_client):
        data = api_client.get("/health").json()
        assert "version" in data

    def test_supported_drugs_listed(self, api_client):
        data = api_client.get("/health").json()
        expected = {"WARFARIN", "CODEINE", "CLOPIDOGREL",
                    "SIMVASTATIN", "AZATHIOPRINE", "FLUOROURACIL"}
        assert set(data["supported_drugs"]) == expected

    def test_supported_genes_listed(self, api_client):
        data = api_client.get("/health").json()
        expected = {"CYP2C9", "CYP2D6", "CYP2C19", "SLCO1B1", "TPMT", "DPYD"}
        assert set(data["supported_genes"]) == expected

    def test_timestamp_present(self, api_client):
        data = api_client.get("/health").json()
        assert "timestamp" in data


# ══════════════════════════════════════════════════════════════════════════
# GET /api/test
# ══════════════════════════════════════════════════════════════════════════

class TestMockEndpoint:

    def test_returns_200(self, api_client):
        resp = api_client.get("/api/test")
        assert resp.status_code == 200

    def test_full_response_schema(self, api_client):
        data = api_client.get("/api/test").json()
        required_keys = [
            "patient_id", "drug", "timestamp", "risk_assessment",
            "pharmacogenomic_profile", "clinical_recommendation",
            "llm_generated_explanation", "quality_metrics",
        ]
        for key in required_keys:
            assert key in data, f"Missing key: {key}"

    def test_risk_assessment_fields(self, api_client):
        ra = api_client.get("/api/test").json()["risk_assessment"]
        assert "risk_label" in ra
        assert "confidence_score" in ra
        assert "severity" in ra
        assert 0.0 <= ra["confidence_score"] <= 1.0

    def test_pgx_profile_fields(self, api_client):
        pgx = api_client.get("/api/test").json()["pharmacogenomic_profile"]
        assert "primary_gene" in pgx
        assert "diplotype" in pgx
        assert "phenotype" in pgx
        assert isinstance(pgx["detected_variants"], list)

    def test_mock_is_high_risk_warfarin(self, api_client):
        data = api_client.get("/api/test").json()
        assert data["drug"] == "WARFARIN"
        # CYP2C9 PM → Toxic (RIFT 2026 schema)
        assert data["risk_assessment"]["risk_label"] == "Toxic"

    def test_explanation_has_summary(self, api_client):
        data = api_client.get("/api/test").json()
        assert data["llm_generated_explanation"]["summary"] != ""

    def test_quality_metrics_vcf_ok(self, api_client):
        data = api_client.get("/api/test").json()
        assert data["quality_metrics"]["vcf_parsing_success"] is True


# ══════════════════════════════════════════════════════════════════════════
# POST /api/analyze — happy paths
# ══════════════════════════════════════════════════════════════════════════

class TestAnalyzeHappyPath:

    def test_returns_200_for_warfarin(self, api_client):
        resp = _post_analyze(api_client, drug="WARFARIN")
        assert resp.status_code == 200

    @pytest.mark.parametrize("drug", [
        "WARFARIN", "CODEINE", "CLOPIDOGREL",
        "SIMVASTATIN", "AZATHIOPRINE", "FLUOROURACIL",
    ])
    def test_all_drugs_return_200(self, api_client, drug):
        resp = _post_analyze(api_client, drug=drug)
        assert resp.status_code == 200, f"{drug} returned {resp.status_code}: {resp.text}"

    def test_patient_id_echoed(self, api_client):
        resp = _post_analyze(api_client, patient_id="HACKATHON_PATIENT")
        assert resp.json()["patient_id"] == "HACKATHON_PATIENT"

    def test_drug_echoed_uppercase(self, api_client):
        resp = _post_analyze(api_client, drug="warfarin")
        assert resp.json()["drug"] == "WARFARIN"

    def test_response_has_all_keys(self, api_client):
        data = _post_analyze(api_client).json()
        for key in ["patient_id", "drug", "timestamp", "risk_assessment",
                    "pharmacogenomic_profile", "clinical_recommendation",
                    "llm_generated_explanation", "quality_metrics"]:
            assert key in data

    def test_confidence_in_range(self, api_client):
        ra = _post_analyze(api_client).json()["risk_assessment"]
        assert 0.0 <= ra["confidence_score"] <= 1.0

    def test_vcf_parsing_success_true(self, api_client):
        data = _post_analyze(api_client).json()
        assert data["quality_metrics"]["vcf_parsing_success"] is True

    def test_primary_gene_set(self, api_client):
        data = _post_analyze(api_client, drug="WARFARIN").json()
        assert data["pharmacogenomic_profile"]["primary_gene"] == "CYP2C9"

    def test_diplotype_not_empty(self, api_client):
        data = _post_analyze(api_client).json()
        assert data["pharmacogenomic_profile"]["diplotype"] != ""

    def test_explanation_summary_not_empty(self, api_client):
        data = _post_analyze(api_client).json()
        assert data["llm_generated_explanation"]["summary"] != ""

    def test_clinical_recommendation_has_dose(self, api_client):
        rec = _post_analyze(api_client).json()["clinical_recommendation"]
        assert "dose_recommendation" in rec
        assert rec["dose_recommendation"] != ""

    def test_severity_is_valid_value(self, api_client):
        data = _post_analyze(api_client).json()
        # RIFT 2026 schema: severity is lowercase
        assert data["risk_assessment"]["severity"] in ("none", "low", "moderate", "high", "critical")

    def test_risk_label_is_valid_value(self, api_client):
        data = _post_analyze(api_client).json()
        # RIFT 2026 schema: required risk_label values
        assert data["risk_assessment"]["risk_label"] in (
            "Safe", "Adjust Dosage", "Toxic", "Ineffective", "Unknown"
        )

    def test_vcfgz_extension_accepted(self, api_client):
        """Backend should accept .vcf.gz filename even if content is plain VCF."""
        resp = _post_analyze(api_client, filename="test.vcf.gz")
        assert resp.status_code == 200

    def test_detected_variants_is_list(self, api_client):
        data = _post_analyze(api_client).json()
        assert isinstance(data["pharmacogenomic_profile"]["detected_variants"], list)


# ══════════════════════════════════════════════════════════════════════════
# POST /api/analyze — validation errors
# ══════════════════════════════════════════════════════════════════════════

class TestAnalyzeValidation:

    def test_missing_patient_id_returns_error(self, api_client):
        resp = api_client.post(
            "/api/analyze",
            data={"drug": "WARFARIN"},
            files=[_vcf_file()],
        )
        assert resp.status_code in (400, 422)

    def test_empty_patient_id_returns_error(self, api_client):
        resp = _post_analyze(api_client, patient_id="   ")
        assert resp.status_code in (400, 422)

    def test_unsupported_drug_returns_400(self, api_client):
        resp = _post_analyze(api_client, drug="ASPIRIN")
        assert resp.status_code == 400
        assert "ASPIRIN" in resp.json().get("detail", "")

    def test_missing_file_returns_422(self, api_client):
        resp = api_client.post(
            "/api/analyze",
            data={"patient_id": "P001", "drug": "WARFARIN"},
        )
        assert resp.status_code == 422

    def test_wrong_file_extension_returns_400(self, api_client):
        resp = api_client.post(
            "/api/analyze",
            data={"patient_id": "P001", "drug": "WARFARIN"},
            files=[("file", ("report.pdf", io.BytesIO(b"not a vcf"), "application/pdf"))],
        )
        assert resp.status_code == 400

    def test_empty_vcf_returns_vcf_error_or_partial(self, api_client):
        """Empty VCF → either 422 or 200 with vcf_parsing_success=false."""
        resp = _post_analyze(api_client, vcf_content=b"", filename="empty.vcf")
        assert resp.status_code in (200, 400, 422)
        if resp.status_code == 200:
            data = resp.json()
            assert data["quality_metrics"]["vcf_parsing_success"] is False

    def test_malformed_vcf_returns_partial_response(self, api_client):
        """Malformed VCF content → backend degrades gracefully (no 500).
        PyVCF3 is lenient on single-line garbage and may still return a valid response;
        we only assert that the backend does NOT crash (status != 500).
        """
        resp = _post_analyze(
            api_client,
            vcf_content=MALFORMED_VCF,
            filename="bad.vcf",
        )
        # Must not be a server error — graceful degradation
        assert resp.status_code in (200, 400, 422)

    def test_drug_case_insensitive(self, api_client):
        """Lowercase drug name should be accepted."""
        resp = _post_analyze(api_client, drug="warfarin")
        assert resp.status_code == 200

    def test_missing_drug_returns_422(self, api_client):
        resp = api_client.post(
            "/api/analyze",
            data={"patient_id": "P001"},
            files=[_vcf_file()],
        )
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════
# General
# ══════════════════════════════════════════════════════════════════════════

class TestGeneralApi:

    def test_unknown_route_returns_404(self, api_client):
        resp = api_client.get("/api/does_not_exist")
        assert resp.status_code == 404

    def test_response_content_type_json(self, api_client):
        resp = api_client.get("/health")
        assert "application/json" in resp.headers.get("content-type", "")

    def test_docs_endpoint_available(self, api_client):
        resp = api_client.get("/docs")
        assert resp.status_code == 200

    def test_openapi_schema_available(self, api_client):
        resp = api_client.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert "paths" in schema
        assert "/api/analyze" in schema["paths"]
        assert "/api/test" in schema["paths"]
        assert "/health" in schema["paths"]
