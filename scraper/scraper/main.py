import os
import hashlib
import pandas as pd
import requests
from jobspy import scrape_jobs
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

SEARCH_QUERIES = [
    "Software Engineer OR Web Developer",
    "Data Analyst OR Business Intelligence",
    "Management Trainee OR ODP",
    "Operations Associate OR Project Officer"
]

def generate_hash(company: str, title: str) -> str:
    raw = f"{str(company).strip().lower()}_{str(title).strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def classify_cluster(title: str) -> str:
    t = str(title).lower()
    if any(k in t for k in ["management trainee", "mt ", "odp", "bflp", "mdp", "graduate program", "leadership"]):
        return "MT/ODP"
    if any(k in t for k in ["data", "analyst", "bi ", "business intelligence", "machine learning", "digital marketing"]):
        return "Data/Digital"
    if any(k in t for k in ["software", "developer", "web", "frontend", "backend", "full stack", "ui/ux", "qa", "it ", "programmer", "engineer"]):
        return "IT/Tech"
    if any(k in t for k in ["operations", "operational", "project", "product", "supply chain", "scrum"]):
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
    for query in SEARCH_QUERIES:
        print(f"Menarik lowongan: {query}...")
        try:
            df = scrape_jobs(
                site_name=["linkedin", "indeed"],
                search_term=query,
                location="Indonesia",
                results_wanted=15,
                hours_old=48,
                country_indeed="Indonesia"
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

        ext_hash = generate_hash(company, title)
        if ext_hash in seen_hashes:
            continue
        seen_hashes.add(ext_hash)

        cluster = classify_cluster(title)
        if cluster == "Other":
            continue

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
    for job in new_jobs[:12]:
        lines.append(
            f"• <b>{job['title']}</b> — {job['company']}\n"
            f"  [{job['role_cluster']} | {job['location']} | {job['work_mode']}] "
            f"<a href='{job['job_url']}'>Lamar &rarr;</a>"
        )

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
