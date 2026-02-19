"""Quick smoke-test of all 6 drug endpoints against sample.vcf."""
import httpx

DRUGS = ["CODEINE", "WARFARIN", "CLOPIDOGREL", "SIMVASTATIN", "AZATHIOPRINE", "FLUOROURACIL"]

with open("tests/sample.vcf", "rb") as f:
    vcf_bytes = f.read()

print(f"{'DRUG':<16} {'DIPLOTYPE':<14} {'PHENOTYPE':<35} {'RISK':<15} {'CONF':>5}")
print("-" * 90)
for drug in DRUGS:
    resp = httpx.post(
        "http://localhost:8000/api/analyze",
        data={"patient_id": "P001", "drug": drug},
        files={"file": ("sample.vcf", vcf_bytes, "text/plain")},
        timeout=30,
    )
    d = resp.json()
    pgx = d["pharmacogenomic_profile"]
    risk = d["risk_assessment"]
    print(
        f"{drug:<16} {pgx['diplotype']:<14} {pgx['phenotype']:<35} "
        f"{risk['risk_label']:<15} {risk['confidence_score']:>5.0%}"
    )
