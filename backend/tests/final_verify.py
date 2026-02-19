"""Final end-to-end verification of all endpoints."""
import httpx

BASE = "http://localhost:8000"

# 1. Health
h = httpx.get(f"{BASE}/health").json()
print("HEALTH :", h["status"], "|", h["version"])

# 2. Mock test endpoint
t = httpx.get(f"{BASE}/api/test").json()
print("TEST   :", t["patient_id"], "|", t["drug"], "|", t["risk_assessment"]["risk_label"])
print()

# 3. Full pipeline — all 6 drugs
drugs = ["WARFARIN", "CODEINE", "CLOPIDOGREL", "SIMVASTATIN", "AZATHIOPRINE", "FLUOROURACIL"]
with open("tests/sample.vcf", "rb") as f:
    vcf = f.read()

header = f"{'DRUG':<16} {'GENE':<10} {'DIPLOTYPE':<12} {'PHENOTYPE':<34} {'RISK':<16} {'CONF':>5} {'VCF':>4}"
print(header)
print("-" * len(header))

all_ok = True
for drug in drugs:
    resp = httpx.post(
        f"{BASE}/api/analyze",
        data={"patient_id": "P001", "drug": drug},
        files={"file": ("sample.vcf", vcf, "text/plain")},
        timeout=30,
    )
    assert resp.status_code == 200, f"{drug}: HTTP {resp.status_code}"
    d    = resp.json()
    pgx  = d["pharmacogenomic_profile"]
    risk = d["risk_assessment"]
    qm   = d["quality_metrics"]
    vcf_ok = "✓" if qm["vcf_parsing_success"] else "✗"
    conf = f"{int(risk['confidence_score']*100)}%"
    print(
        f"{drug:<16} {pgx['primary_gene']:<10} {pgx['diplotype']:<12} "
        f"{pgx['phenotype']:<34} {risk['risk_label']:<16} {conf:>5} {vcf_ok:>4}"
    )
    if not qm["vcf_parsing_success"] or not risk["risk_label"]:
        all_ok = False

print()
print("All endpoints passed:", all_ok)
