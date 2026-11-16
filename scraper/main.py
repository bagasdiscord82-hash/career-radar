import os
import re
import hashlib
import pandas as pd
import requests
from jobspy import scrape_jobs
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Kata kunci luas: IT, Data, Social Media, MT/Semua Jurusan, Operations & Lowongan Aktif 48 Jam
SEARCH_QUERIES = [
    {
        "term": "Software Engineer OR Web Developer OR UI UX",
        "google_term": "lowongan kerja Software Engineer Web Developer UI UX Indonesia"
    },
    {
        "term": "Data Analyst OR Business Intelligence OR Digital Marketing",
        "google_term": "lowongan kerja Data Analyst Business Intelligence Digital Marketing Indonesia"
    },
    {
        "term": "Social Media OR Content Creator OR Copywriter OR Creative",
        "google_term": "lowongan Social Media Content Creator Copywriter Indonesia"
    },
    {
        "term": "Management Trainee OR ODP OR BFLP OR Fresh Graduate",
        "google_term": "lowongan kerja semua jurusan fresh graduate management trainee Indonesia"
    },
    {
        "term": "Operations OR Project Officer OR Business Development OR Admin",
        "google_term": "lowongan kerja semua jurusan admin staff officer Indonesia"
    },
    {
        "term": "Staff OR Associate OR Specialist",
        "google_term": "lowongan kerja terbaru hari ini semua jurusan Indonesia"
    },
    {
        "term": "Surabaya OR Malang",
        "google_term": "lowongan kerja terbaru Surabaya Malang semua jurusan"
    }
]

# Daftar kata kunci profesi berlisensi / sekolah khusus / lapangan yang dikecualikan
EXCLUDED_PATTERNS = [
    # Medis, Kesehatan & Farmasi
    r"\bdokter\b", r"\bdoctor\b", r"\bphysician\b", r"\bdentist\b", r"\bveterinarian\b",
    r"\bapoteker\b", r"\bpharmacist\b", r"\bfarmasi\b", r"\bkefarmasian\b", r"\bttk\b",
    r"\bperawat\b", r"\bnurse\b", r"\bners\b", r"\bbidan\b", r"\bmidwife\b",
    r"\bradiografer\b", r"\bfisioterapis\b", r"\bphysiotherapist\b", r"\bahli gizi\b",
    r"\bnutritionist\b", r"\brekam medis\b", r"\banalis kesehatan\b", r"\blaboratorium klinik\b",
    # Hukum & Kenotariatan Khusus
    r"\bnotaris\b", r"\bnotary\b", r"\badvokat\b", r"\bpengacara\b", r"\blawyer\b", r"\bppat\b",
    # Teknik Fisik, Konstruksi & Tambang Khusus
    r"\barsitek\b", r"\bteknik sipil\b", r"\bcivil engineer\b", r"\bquantity surveyor\b",
    r"\bteknik kimia\b", r"\bchemical engineer\b", r"\bpertambangan\b", r"\bmining\b",
    r"\bgeologi\b", r"\bgeologist\b", r"\bperminyakan\b", r"\bpetroleum\b",
    r"\balat berat\b", r"\bmekanik\b", r"\bwelder\b", r"\bjuru las\b", r"\bteknisi ac\b",
    # Pendidikan Formal, Keagamaan & Penerbangan/Pelayaran
    r"\bguru\b", r"\bteacher\b", r"\bdosen\b", r"\blecturer\b", r"\bustadz\b", r"\bpendeta\b",
    r"\bpilot\b", r"\bpramugari\b", r"\bpramugara\b", r"\bflight attendant\b", r"\bnakhoda\b", r"\bpelaut\b",
    # Operasional Lapangan Non-Kantor
    r"\bchef\b", r"\bkoki\b", r"\bbarista\b", r"\bsopir\b", r"\bdriver\b",
    r"\bkurir\b", r"\bcourier\b", r"\bsatpam\b", r"\bsecurity guard\b", r"\bcleaning service\b"
]

def is_excluded_role(title: str) -> bool:
    t = str(title).lower()
    for pattern in EXCLUDED_PATTERNS:
        if re.search(pattern, t):
            return True
    # Blokir "Architect" bangunan, tapi izinkan "Solutions/Software/Data/Cloud Architect"
    if re.search(r"\barchitect\b", t):
        allowed_tech = ["software", "solution", "data", "cloud", "system", "enterprise", "it", "network", "security", "web"]
        if not any(k in t for k in allowed_tech):
            return True
    return False

def generate_hash(company: str, title: str) -> str:
    raw = f"{str(company).strip().lower()}_{str(title).strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def classify_cluster(title: str) -> str:
    t = str(title).lower()
    if any(k in t for k in ["management trainee", "mt ", "odp", "bflp", "mdp", "graduate program", "leadership", "semua jurusan", "fresh graduate"]):
        return "MT/ODP"
    if any(k in t for k in ["data", "analyst", "bi ", "business intelligence", "machine learning", "digital marketing", "social media", "content", "copywriter", "seo", "creative", "brand", "marketing", "community"]):
        return "Data/Digital"
    if any(k in t for k in ["software", "developer", "web", "frontend", "backend", "full stack", "fullstack", "ui/ux", "ui ux", "qa", "it ", "programmer", "engineer", "devops", "cloud", "system", "mobile"]):
        return "IT/Tech"
    if any(k in t for k in ["operations", "operational", "project", "product", "supply chain", "scrum", "admin", "hr", "human resource", "recruitment", "business development", "sales", "account executive", "customer", "general affair", "finance"]):
        return "Operations"
    return "Other"

def detect_work_mode(location: str, is_remote: bool) -> str:
    loc = str(location).lower()
    if is_remote or "remote" in loc:
        return "Remote"
    if "hybrid" in loc:
        return "Hybrid"
    return "Onsite"

def extract_jobs() -> pd.DataFrame:
    all_frames = []
    for item in SEARCH_QUERIES:
        query = item["term"]
        g_query = item["google_term"]
        print(f"Menarik lowongan: {query}...")
        try:
            df = scrape_jobs(
                site_name=["linkedin", "google"],
                search_term=query,
                google_search_term=g_query,
                location="Indonesia",
                results_wanted=25,
                hours_old=48
            )
            if df is not None and not df.empty:
                all_frames.append(df)
        except Exception as e:
            print(f"Peringatan pada kueri '{query}': {e}")

    if not all_frames:
        return pd.DataFrame()
    return pd.concat(all_frames, ignore_index=True)

def transform_and_load(df: pd.DataFrame, supabase: Client) -> list:
    if df.empty:
        return []

    records = []
    seen_hashes = set()

    for _, row in df.iterrows():
        title = str(row.get("title", "")).strip()
        company = str(row.get("company", "")).strip()
        job_url = str(row.get("job_url", "")).strip()

        if not title or title == "nan" or not company or company == "nan" or not job_url:
            continue

        # Lewati lowongan berlisensi / pendidikan khusus
        if is_excluded_role(title):
            continue

        ext_hash = generate_hash(company, title)
        if ext_hash in seen_hashes:
            continue
        seen_hashes.add(ext_hash)

        cluster = classify_cluster(title)

        location = str(row.get("location", "Indonesia"))
        if location == "nan":
            location = "Indonesia"

        is_remote = bool(row.get("is_remote", False)) if not pd.isna(row.get("is_remote")) else False

        records.append({
            "external_hash": ext_hash,
            "title": title[:250],
            "company": company[:250],
            "role_cluster": cluster,
            "location": location[:140],
            "work_mode": detect_work_mode(location, is_remote),
            "source": str(row.get("site", "Portal")).capitalize(),
            "job_url": job_url
        })

    if not records:
        return []

    existing_res = supabase.table("job_listings").select("external_hash").in_(
        "external_hash", [r["external_hash"] for r in records]
    ).execute()
    existing_hashes = {item["external_hash"] for item in (existing_res.data or [])}

    new_records = [r for r in records if r["external_hash"] not in existing_hashes]

    if new_records:
        supabase.table("job_listings").upsert(new_records, on_conflict="external_hash").execute()

    return new_records

def send_telegram_digest(new_jobs: list):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not new_jobs:
        return

    lines = [f"🎯 <b>CareerRadar Daily Digest ({len(new_jobs)} Lowongan Baru)</b>\n"]
    # Batasi 15 sorotan di Telegram agar tidak melewati batas karakter API Telegram
    for job in new_jobs[:15]:
        lines.append(
            f"• <b>{job['title']}</b> — {job['company']}\n"
            f"  [{job['role_cluster']} | {job['location']} | {job['work_mode']}] "
            f"<a href='{job['job_url']}'>Lamar &rarr;</a>"
        )

    if len(new_jobs) > 15:
        lines.append(f"\n<i>...dan {len(new_jobs) - 15} lowongan lainnya sudah tersimpan di Web Dashboard.</i>")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": "\n".join(lines),
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }, timeout=15)

if __name__ == "__main__":
    supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    raw_df = extract_jobs()
    inserted_jobs = transform_and_load(raw_df, supabase_client)
    print(f"Selesai. {len(inserted_jobs)} lowongan baru disimpan ke Supabase.")
    send_telegram_digest(inserted_jobs)
