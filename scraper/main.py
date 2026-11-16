import os
import re
import hashlib
from datetime import datetime, timedelta, timezone
import pandas as pd
import requests
from jobspy import scrape_jobs
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Strategi pencarian bertingkat yang dikalibrasi dengan profil CV Bagas Dwi Ardianto:
# 1. Malang Raya (Semua bidang relevan & semua jurusan)
# 2. Surabaya & Jatim (Creative, UI/UX, IT Support, Operations, MT)
# 3. Nasional & Remote (UI/UX Figma, Social Media, IT/Web, MT/ODP IPK >3.5)
SEARCH_PLANS = [
    {
        "location": "Malang, East Java, Indonesia",
        "tag_city": "Malang",
        "term": "Graphic Designer OR Social Media OR Content Creator OR Creative OR Admin",
        "google_term": "lowongan kerja Graphic Designer Social Media Content Admin Malang",
        "results": 25
    },
    {
        "location": "Malang, East Java, Indonesia",
        "tag_city": "Malang",
        "term": "IT Support OR UI UX OR Web Developer OR Staff OR Operations OR Event",
        "google_term": "lowongan kerja IT Support Staff Operations semua jurusan Malang",
        "results": 25
    },
    {
        "location": "Surabaya, East Java, Indonesia",
        "tag_city": "Surabaya",
        "term": "UI UX OR Graphic Designer OR Social Media OR IT Support OR Management Trainee",
        "google_term": "lowongan kerja UI UX Graphic Design IT Support Fresh Graduate Surabaya",
        "results": 20
    },
    {
        "location": "Indonesia",
        "tag_city": "",
        "term": "UI UX Designer OR Product Designer OR Graphic Designer OR Social Media Specialist",
        "google_term": "lowongan kerja UI UX Designer Social Media Remote Indonesia",
        "results": 20
    },
    {
        "location": "Indonesia",
        "tag_city": "",
        "term": "Management Trainee OR ODP OR BFLP OR IT Support OR Junior Web Developer",
        "google_term": "lowongan Management Trainee ODP BFLP semua jurusan Fresh Graduate Indonesia",
        "results": 20
    }
]

# Pengecualian profesi berlisensi / sekolah khusus / operasional non-kantor
EXCLUDED_PROFESSION_PATTERNS = [
    r"\bdokter\b", r"\bdoctor\b", r"\bphysician\b", r"\bdentist\b", r"\bveterinarian\b",
    r"\bapoteker\b", r"\bpharmacist\b", r"\bfarmasi\b", r"\bkefarmasian\b", r"\bttk\b",
    r"\bperawat\b", r"\bnurse\b", r"\bners\b", r"\bbidan\b", r"\bmidwife\b",
    r"\bradiografer\b", r"\bfisioterapis\b", r"\bphysiotherapist\b", r"\bahli gizi\b",
    r"\bnutritionist\b", r"\brekam medis\b", r"\banalis kesehatan\b", r"\blaboratorium klinik\b",
    r"\bnotaris\b", r"\bnotary\b", r"\badvokat\b", r"\bpengacara\b", r"\blawyer\b", r"\bppat\b",
    r"\barsitek\b", r"\bteknik sipil\b", r"\bcivil engineer\b", r"\bquantity surveyor\b",
    r"\bteknik kimia\b", r"\bchemical engineer\b", r"\bpertambangan\b", r"\bmining\b",
    r"\bgeologi\b", r"\bgeologist\b", r"\bperminyakan\b", r"\bpetroleum\b",
    r"\balat berat\b", r"\bmekanik\b", r"\bwelder\b", r"\bjuru las\b", r"\bteknisi ac\b",
    r"\bguru\b", r"\bteacher\b", r"\bdosen\b", r"\blecturer\b", r"\bustadz\b", r"\bpendeta\b",
    r"\bpilot\b", r"\bpramugari\b", r"\bpramugara\b", r"\bflight attendant\b", r"\bnakhoda\b", r"\bpelaut\b",
    r"\bchef\b", r"\bkoki\b", r"\bbarista\b", r"\bsopir\b", r"\bdriver\b",
    r"\bkurir\b", r"\bcourier\b", r"\bsatpam\b", r"\bsecurity guard\b", r"\bcleaning service\b"
]

# Pengecualian level senior/manajerial agar fokus pada Fresh Graduate / Junior / Staff / MT
EXCLUDED_SENIORITY_PATTERNS = [
    r"\bsenior\b", r"\bsr\.?\b", r"\blead\b", r"\bteam leader\b", r"\bmanager\b",
    r"\bmanajer\b", r"\bhead of\b", r"\bdirector\b", r"\bdirektur\b", r"\bvp\b",
    r"\bvice president\b", r"\bprincipal\b", r"\bsupervisor\b", r"\bspv\b", r"\bchief\b"
]

def is_excluded_role(title: str) -> bool:
    t = str(title).lower()
    for pattern in EXCLUDED_PROFESSION_PATTERNS:
        if re.search(pattern, t):
            return True

    # Kecualikan posisi senior/manajer, kecuali program Management Trainee (MT/MDP)
    if not any(mt in t for mt in ["management trainee", "mt ", "mdp", "odp", "bflp"]):
        for s_pattern in EXCLUDED_SENIORITY_PATTERNS:
            if re.search(s_pattern, t):
                return True

    if re.search(r"\barchitect\b", t):
        allowed_tech = ["software", "solution", "data", "cloud", "system", "it", "web"]
        if not any(k in t for k in allowed_tech):
            return True
    return False

def calculate_cv_match_score(title: str, location: str, work_mode: str) -> int:
    """Menghitung skor relevansi (0-100) berdasarkan skill & pengalaman CV Bagas."""
    t = str(title).lower()
    loc = str(location).lower()
    score = 45  # Skor dasar untuk posisi entry-level/umum yang lolos filter

    # 1. Kecocokan Kompetensi Inti CV (Bobot Tinggi: +35)
    tier1_keywords = [
        "ui/ux", "ui ux", "figma", "graphic design", "desain grafis", "social media",
        "visual content", "content creator", "it support", "helpdesk", "technical support",
        "network", "jaringan", "event", "management trainee", "odp", "bflp"
    ]
    # 2. Kecocokan Kompetensi Pendukung CV (Bobot Menengah: +22)
    tier2_keywords = [
        "creative", "canva", "digital marketing", "e-commerce", "ecommerce", "marketplace",
        "admin", "administrasi", "data entry", "operations", "operasional", "project officer",
        "web developer", "frontend", "front-end", "junior developer", "it staff", "staff it",
        "fresh graduate", "semua jurusan", "copywriter", "brand"
    ]

    if any(k in t for k in tier1_keywords):
        score += 35
    elif any(k in t for k in tier2_keywords):
        score += 22

    # 3. Bonus Lokasi Strategis (Malang Raya / Remote)
    if "malang" in loc or "batu" in loc:
        score += 18
    elif work_mode == "Remote":
        score += 14
    elif any(c in loc for c in ["surabaya", "sidoarjo", "gresik", "jawa timur", "east java"]):
        score += 8

    return min(score, 99)

def generate_hash(company: str, title: str) -> str:
    raw = f"{str(company).strip().lower()}_{str(title).strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def detect_real_source(site_raw: str, job_url: str) -> str:
    url = str(job_url).lower()
    if "jobstreet" in url:
        return "JobStreet"
    if "glints" in url:
        return "Glints"
    if "kalibrr" in url:
        return "Kalibrr"
    if "dealls" in url:
        return "Dealls"
    if "linkedin" in url:
        return "LinkedIn"
    if "karir.com" in url:
        return "Karir.com"
    if "indeed" in url:
        return "Indeed"
    s = str(site_raw).strip().capitalize()
    return s if s and s != "Nan" else "Google Jobs"

def classify_cluster(title: str) -> str:
    t = str(title).lower()
    if any(k in t for k in ["management trainee", "mt ", "odp", "bflp", "mdp", "graduate program", "leadership", "semua jurusan", "fresh graduate"]):
        return "MT/ODP"
    if any(k in t for k in ["social media", "graphic design", "desain grafis", "content", "creative", "visual", "copywriter", "digital marketing", "e-commerce", "marketplace", "brand", "data", "analyst", "seo"]):
        return "Data/Digital"
    if any(k in t for k in ["ui/ux", "ui ux", "figma", "it support", "helpdesk", "technical support", "network", "jaringan", "software", "developer", "web", "frontend", "backend", "full stack", "qa", "it ", "programmer", "system"]):
        return "IT/Tech"
    if any(k in t for k in ["event", "operations", "operasional", "project", "product", "admin", "administrasi", "logistics", "logistik", "hr", "recruitment", "business development", "general affair"]):
        return "Operations"
    return "Other"

def detect_work_mode(location: str, title: str, is_remote: bool) -> str:
    combined = f"{location} {title}".lower()
    if is_remote or "remote" in combined or "wfh" in combined:
        return "Remote"
    if "hybrid" in combined:
        return "Hybrid"
    return "Onsite"

def refresh_unapplied_radar(supabase: Client, max_age_hours: int = 48):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
    applied_res = supabase.table("applications").select("job_id").neq("status", "Wishlist").execute()
    protected_ids = {row["job_id"] for row in (applied_res.data or [])}

    old_jobs = supabase.table("job_listings").select("id").lt("created_at", cutoff).execute()
    stale_ids = [row["id"] for row in (old_jobs.data or []) if row["id"] not in protected_ids]

    if stale_ids:
        for i in range(0, len(stale_ids), 100):
            batch = stale_ids[i:i + 100]
            supabase.table("job_listings").delete().in_("id", batch).execute()
        print(f"Auto-refresh: {len(stale_ids)} lowongan lama (> {max_age_hours} jam) dibersihkan.")

def extract_jobs() -> pd.DataFrame:
    all_frames = []
    for plan in SEARCH_PLANS:
        print(f"Menarik lowongan [{plan['location']}]: {plan['term']}...")
        try:
            df = scrape_jobs(
                site_name=["linkedin", "google"],
                search_term=plan["term"],
                google_search_term=plan["google_term"],
                location=plan["location"],
                results_wanted=plan["results"],
                hours_old=48
            )
            if df is not None and not df.empty:
                df["_tag_city"] = plan["tag_city"]
                all_frames.append(df)
        except Exception as e:
            print(f"Peringatan pada pencarian '{plan['location']}': {e}")

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

        if is_excluded_role(title):
            continue

        ext_hash = generate_hash(company, title)
        if ext_hash in seen_hashes:
            continue
        seen_hashes.add(ext_hash)

        raw_loc = str(row.get("location", "")).strip()
        tag_city = str(row.get("_tag_city", "")).strip()
        if not raw_loc or raw_loc == "nan" or raw_loc.lower() == "indonesia":
            location = f"{tag_city}, East Java" if tag_city else "Indonesia"
        else:
            location = raw_loc

        is_remote = bool(row.get("is_remote", False)) if not pd.isna(row.get("is_remote")) else False
        work_mode = detect_work_mode(location, title, is_remote)
        real_source = detect_real_source(row.get("site", ""), job_url)
        match_score = calculate_cv_match_score(title, location, work_mode)

        records.append({
            "external_hash": ext_hash,
            "title": title[:250],
            "company": company[:250],
            "role_cluster": classify_cluster(title),
            "location": location[:140],
            "work_mode": work_mode,
            "source": real_source,
            "job_url": job_url,
            "_match_score": match_score
        })

    if not records:
        return []

    # Urutkan dari kecocokan CV tertinggi & prioritas Malang
    records.sort(key=lambda x: x["_match_score"], reverse=True)

    existing_res = supabase.table("job_listings").select("external_hash").in_(
        "external_hash", [r["external_hash"] for r in records]
    ).execute()
    existing_hashes = {item["external_hash"] for item in (existing_res.data or [])}

    new_records = [r for r in records if r["external_hash"] not in existing_hashes]

    if new_records:
        # Simpan skor sementara untuk notifikasi Telegram lalu bersihkan field internal sebelum upsert SQL
        telegram_batch = [dict(r) for r in new_records]
        for r in new_records:
            r.pop("_match_score", None)
        supabase.table("job_listings").upsert(new_records, on_conflict="external_hash").execute()
        return telegram_batch

    return []

def send_telegram_digest(new_jobs: list):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not new_jobs:
        return

    lines = [f"🎯 <b>CareerRadar Daily Digest ({len(new_jobs)} Lowongan Baru)</b>\n"]
    for job in new_jobs[:15]:
        score = job.get("_match_score", 70)
        pin = "📍 " if "malang" in job["location"].lower() else "• "
        lines.append(
            f"{pin}<b>{job['title']}</b> — {job['company']} <i>({score}% Match)</i>\n"
            f"  [{job['role_cluster']} | {job['location']} | {job['source']}] "
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
    refresh_unapplied_radar(supabase_client, max_age_hours=48)
    raw_df = extract_jobs()
    inserted_jobs = transform_and_load(raw_df, supabase_client)
    print(f"Selesai. {len(inserted_jobs)} lowongan baru disimpan ke Supabase.")
    send_telegram_digest(inserted_jobs)
