import os
import re
import time
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

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7"
}

# 1. Rencana Pencarian LinkedIn & Indeed Indonesia (via JobSpy)
JOBSPY_PLANS = [
    {
        "location": "Malang, East Java, Indonesia",
        "tag_city": "Malang",
        "term": "Graphic Designer OR Social Media OR Content Creator OR Creative OR Admin",
        "results": 20
    },
    {
        "location": "Malang, East Java, Indonesia",
        "tag_city": "Malang",
        "term": "IT Support OR UI UX OR Web Developer OR Staff OR Operations OR Event",
        "results": 20
    },
    {
        "location": "Surabaya, East Java, Indonesia",
        "tag_city": "Surabaya",
        "term": "UI UX OR Graphic Designer OR Social Media OR IT Support OR Management Trainee",
        "results": 15
    },
    {
        "location": "Indonesia",
        "tag_city": "",
        "term": "UI UX Designer OR Graphic Designer OR Social Media Specialist OR Management Trainee",
        "results": 15
    }
]

# 2. Rencana Pencarian JobStreet Indonesia (Direct API v5)
JOBSTREET_PLANS = [
    {"keywords": "Graphic Designer", "where": "Malang", "tag_city": "Malang"},
    {"keywords": "Social Media", "where": "Malang", "tag_city": "Malang"},
    {"keywords": "IT Support", "where": "Malang", "tag_city": "Malang"},
    {"keywords": "Admin", "where": "Malang", "tag_city": "Malang"},
    {"keywords": "UI UX Designer", "where": "Indonesia", "tag_city": ""},
    {"keywords": "Management Trainee", "where": "Indonesia", "tag_city": ""},
    {"keywords": "Social Media Specialist", "where": "Surabaya", "tag_city": "Surabaya"}
]

# 3. Kata Kunci Pencarian Kalibrr Indonesia (Direct JSON Board API)
KALIBRR_KEYWORDS = [
    "UI UX",
    "Graphic Design",
    "Social Media",
    "IT Support",
    "Management Trainee",
    "Malang"
]

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
    t = str(title).lower()
    loc = str(location).lower()
    score = 45

    tier1_keywords = [
        "ui/ux", "ui ux", "figma", "graphic design", "desain grafis", "social media",
        "visual content", "content creator", "it support", "helpdesk", "technical support",
        "network", "jaringan", "event", "management trainee", "odp", "bflp"
    ]
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

def detect_work_mode(location: str, title: str, is_remote: bool = False) -> str:
    combined = f"{location} {title}".lower()
    if is_remote or "remote" in combined or "wfh" in combined or "work from home" in combined:
        return "Remote"
    if "hybrid" in combined:
        return "Hybrid"
    return "Onsite"

# ==============================================================================
# SCRAPER 1: JOBSTREET INDONESIA (API v5)
# ==============================================================================
def fetch_jobstreet_jobs() -> list:
    results = []
    for plan in JOBSTREET_PLANS:
        try:
            params = {
                "siteKey": "ID-Main",
                "sourcesystem": "houston",
                "where": plan["where"],
                "keywords": plan["keywords"],
                "page": 1,
                "pageSize": 25,
                "sortmode": "ListedDate"
            }
            resp = requests.get(
                "https://id.jobstreet.com/api/jobsearch/v5/search",
                params=params,
                headers=HTTP_HEADERS,
                timeout=15
            )
            if resp.status_code != 200:
                print(f"[JobStreet] HTTP {resp.status_code} untuk '{plan['keywords']}'")
                continue

            items = resp.json().get("data", [])
            print(f"[JobStreet] '{plan['keywords']}' ({plan['where']}): {len(items)} lowongan")

            for item in items:
                job_id = item.get("id")
                title = str(item.get("title", "")).strip()
                advertiser = item.get("advertiser") or {}
                company = str(item.get("companyName") or advertiser.get("description") or "Perusahaan di JobStreet").strip()

                locs = item.get("locations") or []
                loc_label = locs[0].get("label", "") if locs and isinstance(locs[0], dict) else ""
                if not loc_label:
                    loc_label = f"{plan['tag_city']}, East Java" if plan["tag_city"] else "Indonesia"

                arrangements = str(item.get("workArrangements", "")).lower()
                is_rem = "remote" in arrangements
                work_mode = detect_work_mode(f"{loc_label} {arrangements}", title, is_rem)

                if job_id and title:
                    results.append({
                        "title": title,
                        "company": company,
                        "location": loc_label,
                        "work_mode": work_mode,
                        "source": "JobStreet",
                        "job_url": f"https://id.jobstreet.com/id/job/{job_id}"
                    })
            time.sleep(0.8)
        except Exception as e:
            print(f"[JobStreet] Error '{plan['keywords']}': {e}")
    return results

# ==============================================================================
# SCRAPER 2: KALIBRR INDONESIA (DIRECT JSON BOARD API)
# ==============================================================================
def fetch_kalibrr_jobs() -> list:
    results = []
    for kw in KALIBRR_KEYWORDS:
        try:
            params = {
                "text": kw,
                "limit": 30,
                "offset": 0
            }
            resp = requests.get(
                "https://www.kalibrr.com/kjs/job_board/search",
                params=params,
                headers=HTTP_HEADERS,
                timeout=15
            )
            if resp.status_code != 200:
                print(f"[Kalibrr] HTTP {resp.status_code} untuk '{kw}'")
                continue

            jobs = resp.json().get("jobs", [])
            count_id = 0
            for j in jobs:
                g_loc = j.get("google_location") or {}
                addr_comps = g_loc.get("address_components") or {}
                country = str(addr_comps.get("country", "")).lower()
                city = str(addr_comps.get("city") or addr_comps.get("region") or "").strip()
                raw_loc_str = f"{city} {country}".lower()

                # Filter hanya lowongan di Indonesia
                if "indonesia" not in raw_loc_str and not any(c in raw_loc_str for c in ["jakarta", "malang", "surabaya", "bandung", "yogyakarta", "tangerang", "bekasi", "depok", "bogor", "semarang", "bali"]):
                    continue

                job_id = j.get("id")
                title = str(j.get("name", "")).strip()
                company_obj = j.get("company") or {}
                company = str(j.get("company_name") or company_obj.get("name") or "Perusahaan di Kalibrr").strip()
                comp_code = str(company_obj.get("code") or "company").strip()
                slug = str(j.get("slug") or "job").strip()
                is_wfh = bool(j.get("is_work_from_home", False))

                loc_display = f"{city}, Indonesia" if city else "Indonesia"
                work_mode = detect_work_mode(loc_display, title, is_wfh)

                if job_id and title:
                    count_id += 1
                    results.append({
                        "title": title,
                        "company": company,
                        "location": loc_display,
                        "work_mode": work_mode,
                        "source": "Kalibrr",
                        "job_url": f"https://www.kalibrr.com/c/{comp_code}/jobs/{job_id}/{slug}"
                    })
            print(f"[Kalibrr] '{kw}': {count_id} lowongan Indonesia")
            time.sleep(0.8)
        except Exception as e:
            print(f"[Kalibrr] Error '{kw}': {e}")
    return results

# ==============================================================================
# SCRAPER 3 & 4: LINKEDIN + INDEED INDONESIA (JOBSPY)
# ==============================================================================
def fetch_jobspy_jobs() -> list:
    results = []
    for plan in JOBSPY_PLANS:
        print(f"[LinkedIn & Indeed] Menarik [{plan['location']}]: {plan['term']}...")
        try:
            df = scrape_jobs(
                site_name=["linkedin", "indeed"],
                search_term=plan["term"],
                location=plan["location"],
                country_indeed="Indonesia",
                results_wanted=plan["results"],
                hours_old=72
            )
            if df is not None and not df.empty:
                by_site = df["site"].value_counts().to_dict() if "site" in df.columns else {}
                print(f"  -> Hasil per portal: {by_site}")
                for _, row in df.iterrows():
                    title = str(row.get("title", "")).strip()
                    company = str(row.get("company", "")).strip()
                    job_url = str(row.get("job_url", "")).strip()
                    site_raw = str(row.get("site", "")).strip().lower()

                    if not title or title == "nan" or not company or company == "nan" or not job_url:
                        continue

                    raw_loc = str(row.get("location", "")).strip()
                    if not raw_loc or raw_loc == "nan" or raw_loc.lower() == "indonesia":
                        location = f"{plan['tag_city']}, East Java" if plan["tag_city"] else "Indonesia"
                    else:
                        location = raw_loc

                    is_remote = bool(row.get("is_remote", False)) if not pd.isna(row.get("is_remote")) else False
                    work_mode = detect_work_mode(location, title, is_remote)
                    source_label = "Indeed" if "indeed" in site_raw else "LinkedIn"

                    results.append({
                        "title": title,
                        "company": company,
                        "location": location,
                        "work_mode": work_mode,
                        "source": source_label,
                        "job_url": job_url
                    })
            time.sleep(2.0)
        except Exception as e:
            print(f"[LinkedIn & Indeed] Peringatan pada '{plan['location']}': {e}")
    return results

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

def transform_and_load(raw_jobs: list, supabase: Client) -> list:
    if not raw_jobs:
        return []

    records = []
    seen_hashes = set()

    for item in raw_jobs:
        title = str(item.get("title", "")).strip()
        company = str(item.get("company", "")).strip()
        job_url = str(item.get("job_url", "")).strip()

        if not title or not company or not job_url:
            continue

        if is_excluded_role(title):
            continue

        ext_hash = generate_hash(company, title)
        if ext_hash in seen_hashes:
            continue
        seen_hashes.add(ext_hash)

        location = str(item.get("location", "Indonesia")).strip()
        work_mode = str(item.get("work_mode", "Onsite")).strip()
        source = str(item.get("source", "Portal")).strip()
        match_score = calculate_cv_match_score(title, location, work_mode)

        records.append({
            "external_hash": ext_hash,
            "title": title[:250],
            "company": company[:250],
            "role_cluster": classify_cluster(title),
            "location": location[:140],
            "work_mode": work_mode,
            "source": source,
            "job_url": job_url,
            "_match_score": match_score
        })

    if not records:
        return []

    records.sort(key=lambda x: x["_match_score"], reverse=True)

    existing_hashes = set()
    all_hashes = [r["external_hash"] for r in records]
    for i in range(0, len(all_hashes), 100):
        batch = all_hashes[i:i + 100]
        existing_res = supabase.table("job_listings").select("external_hash").in_("external_hash", batch).execute()
        for row in (existing_res.data or []):
            existing_hashes.add(row["external_hash"])

    new_records = [r for r in records if r["external_hash"] not in existing_hashes]

    if new_records:
        telegram_batch = [dict(r) for r in new_records]
        for r in new_records:
            r.pop("_match_score", None)
        for i in range(0, len(new_records), 100):
            supabase.table("job_listings").upsert(new_records[i:i + 100], on_conflict="external_hash").execute()
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

    js_jobs = fetch_jobstreet_jobs()
    kl_jobs = fetch_kalibrr_jobs()
    li_in_jobs = fetch_jobspy_jobs()

    combined_raw = js_jobs + kl_jobs + li_in_jobs
    print(f"Total mentah terkumpul -> JobStreet: {len(js_jobs)}, Kalibrr: {len(kl_jobs)}, LinkedIn+Indeed: {len(li_in_jobs)}")

    inserted_jobs = transform_and_load(combined_raw, supabase_client)
    print(f"Selesai. {len(inserted_jobs)} lowongan baru unik disimpan ke Supabase.")
    send_telegram_digest(inserted_jobs)
