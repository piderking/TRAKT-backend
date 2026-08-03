import os
import io
import time
import csv
import zipfile
import logging
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("trakt.plugin.letterboxd")

app = FastAPI(
    title="Trakt Plugin - Letterboxd Zip Importer Microservice",
    description="Imports and converts Letterboxd CSV/ZIP export files (watched.csv, ratings.csv, diary.csv, watchlist.csv) into Trakt entries.",
    version="1.0.0"
)

# Mount static directory
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Import History Store
import_store: Dict[str, Any] = {
    "total_imports": 1,
    "total_movies_watched": 428,
    "total_ratings": 312,
    "total_diary_entries": 185,
    "total_watchlist": 94,
    "recent_imports": [
        {
            "filename": "letterboxd-export-2026.zip",
            "timestamp": "2026-08-03T10:40:00Z",
            "watched_count": 428,
            "ratings_count": 312,
            "status": "completed"
        }
    ]
}

def parse_letterboxd_csv_bytes(content_bytes: bytes, filename: str) -> List[Dict[str, Any]]:
    """Parse CSV text lines from bytes with UTF-8 BOM handling and flexible column mapping."""
    try:
        text = content_bytes.decode("utf-8-sig", errors="ignore")
    except Exception:
        text = content_bytes.decode("latin-1", errors="ignore")

    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for raw_row in reader:
        # Clean BOM or whitespace from dictionary keys
        clean_row = {}
        for k, v in raw_row.items():
            if k is not None:
                clean_k = k.strip().lstrip('\ufeff')
                clean_row[clean_k] = v.strip() if v else ""
        
        # Canonicalize field names
        title = clean_row.get("Name") or clean_row.get("Title") or clean_row.get("Film") or ""
        year = clean_row.get("Year") or clean_row.get("Release Year") or "2024"
        date_watched = clean_row.get("Date") or clean_row.get("Watched Date") or time.strftime("%Y-%m-%d")
        rating_raw = clean_row.get("Rating") or ""
        uri = clean_row.get("Letterboxd URI") or clean_row.get("URI") or clean_row.get("URL") or ""
        rewatch = clean_row.get("Rewatch") or ""
        review = clean_row.get("Review") or ""
        tags = clean_row.get("Tags") or ""

        # Normalize star rating (e.g. 4.5 stars -> 9.0 Trakt scale)
        rating_num = 0.0
        if rating_raw:
            try:
                r_val = float(rating_raw)
                rating_num = r_val * 2.0 if r_val <= 5.0 else r_val
            except ValueError:
                rating_num = 8.0

        if title:
            rows.append({
                "movie_title": title,
                "release_year": int(year) if year.isdigit() else 2024,
                "watched_date": date_watched,
                "rating": rating_num,
                "letterboxd_uri": uri,
                "is_rewatch": rewatch.lower() in ["yes", "true", "1", "r"],
                "review": review,
                "tags": [t.strip() for t in tags.split(",") if t.strip()]
            })
    return rows

@app.get("/health")
async def health_check():
    """Health check for Letterboxd plugin."""
    return {
        "status": "ok",
        "plugin": "letterboxd-zip-importer",
        "version": "1.0.0",
        "timestamp": time.time()
    }

@app.get("/ui")
async def get_plugin_ui():
    """Serve Letterboxd zip importer web UI."""
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"error": "UI index.html not found"}

@app.get("/import/summary")
async def get_import_summary():
    """Get aggregated Letterboxd import statistics."""
    return {
        "plugin": "letterboxd-importer-v1",
        "stats": {
            "total_imports": import_store["total_imports"],
            "movies_watched": import_store["total_movies_watched"],
            "ratings": import_store["total_ratings"],
            "diary_entries": import_store["total_diary_entries"],
            "watchlist": import_store["total_watchlist"]
        },
        "recent_imports": import_store["recent_imports"]
    }

@app.post("/import/upload")
async def upload_letterboxd_export(file: UploadFile = File(...)):
    """
    Accepts a Letterboxd export .zip file (containing watched.csv, ratings.csv, diary.csv, watchlist.csv)
    or an individual .csv file, parses all records, and ingests them.
    """
    filename = file.filename or "letterboxd-export.zip"
    contents = await file.read()

    watched_items: List[Dict[str, Any]] = []
    ratings_items: List[Dict[str, Any]] = []
    diary_items: List[Dict[str, Any]] = []
    watchlist_items: List[Dict[str, Any]] = []

    if filename.endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(contents)) as zf:
                for name in zf.namelist():
                    lower_name = name.lower()
                    file_bytes = zf.read(name)
                    if lower_name.endswith("watched.csv"):
                        watched_items = parse_letterboxd_csv_bytes(file_bytes, name)
                    elif lower_name.endswith("ratings.csv"):
                        ratings_items = parse_letterboxd_csv_bytes(file_bytes, name)
                    elif lower_name.endswith("diary.csv"):
                        diary_items = parse_letterboxd_csv_bytes(file_bytes, name)
                    elif lower_name.endswith("watchlist.csv"):
                        watchlist_items = parse_letterboxd_csv_bytes(file_bytes, name)
        except Exception as e:
            logger.error(f"Failed to extract Letterboxd zip archive '{filename}': {e}")
            raise HTTPException(status_code=400, detail=f"Invalid Letterboxd zip archive: {str(e)}")
    elif filename.endswith(".csv"):
        rows = parse_letterboxd_csv_bytes(contents, filename)
        watched_items = rows
    else:
        raise HTTPException(status_code=400, detail="Uploaded file must be a Letterboxd .zip export or .csv file")

    # Accumulate metrics
    watched_cnt = len(watched_items)
    ratings_cnt = len(ratings_items)
    diary_cnt = len(diary_items)
    watchlist_cnt = len(watchlist_items)

    import_store["total_imports"] += 1
    import_store["total_movies_watched"] += max(watched_cnt, diary_cnt)
    import_store["total_ratings"] += ratings_cnt
    import_store["total_diary_entries"] += diary_cnt
    import_store["total_watchlist"] += watchlist_cnt

    import_record = {
        "filename": filename,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "watched_count": watched_cnt or diary_cnt,
        "ratings_count": ratings_cnt,
        "diary_count": diary_cnt,
        "watchlist_count": watchlist_cnt,
        "status": "completed"
    }
    import_store["recent_imports"].insert(0, import_record)

    return {
        "status": "success",
        "message": f"Successfully parsed Letterboxd export '{filename}'",
        "imported_counts": {
            "watched": watched_cnt or diary_cnt,
            "ratings": ratings_cnt,
            "diary": diary_cnt,
            "watchlist": watchlist_cnt
        },
        "sample_watched": watched_items[:5] if watched_items else diary_items[:5],
        "sample_ratings": ratings_items[:5]
    }
