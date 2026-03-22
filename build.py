"""
build.py
--------
Processes the Graduate Employment Survey CSV and generates static JSON files
for the GitHub Pages website.

Usage:
    pip install pandas
    python build.py

Output structure:
    docs/
    └── data/
        ├── metadata.json          # all unis, schools, degrees for dropdowns
        └── courses/
            ├── index.json         # maps slug -> {university, school, degree}
            └── <slug>.json        # one file per unique degree, all years of data

Run this script whenever you get new data, then commit the docs/ folder to GitHub.
"""

import pandas as pd
import json
import math
import os
import re
from pathlib import Path


class SafeJSONEncoder(json.JSONEncoder):
    """
    Converts values that are valid Python but invalid JSON:
        float('nan')  → null
        float('inf')  → null
        pandas NA     → null
    Use this for every json.dump call in this script.
    """
    def default(self, obj):
        try:
            if pd.isna(obj):
                return None
        except (TypeError, ValueError):
            pass
        return super().default(obj)

    def iterencode(self, obj, _one_shot=False):
        return super().iterencode(self._sanitise(obj), _one_shot)

    def _sanitise(self, obj):
        if isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return None
            return obj
        if isinstance(obj, dict):
            return {k: self._sanitise(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [self._sanitise(v) for v in obj]
        return obj


# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

INPUT_CSV = "GraduateEmploymentSurveyNTUNUSSITSMUSUSSSUTD.csv"
OUTPUT_DIR = Path("docs/data")

# Numeric columns that should be cast to float (may contain "na", "N.A.", "**" etc.)
NUMERIC_COLS = [
    "employment_rate_overall",
    "employment_rate_ft_perm",
    "basic_monthly_mean",
    "basic_monthly_median",
    "gross_monthly_mean",
    "gross_monthly_median",
    "gross_mthly_25_percentile",
    "gross_mthly_75_percentile",
]

# Friendly display labels for each metric (used by the frontend)
METRIC_LABELS = {
    "employment_rate_overall":    "Overall Employment Rate (%)",
    "employment_rate_ft_perm":    "Full-Time Permanent Employment Rate (%)",
    "basic_monthly_mean":         "Basic Monthly Mean ($)",
    "basic_monthly_median":       "Basic Monthly Median ($)",
    "gross_monthly_mean":         "Gross Monthly Mean ($)",
    "gross_monthly_median":       "Gross Monthly Median ($)",
    "gross_mthly_25_percentile":  "Gross Monthly 25th Percentile ($)",
    "gross_mthly_75_percentile":  "Gross Monthly 75th Percentile ($)",
}

# Known university name normalizations (catches minor year-to-year naming drift)
UNI_NORMALIZATIONS = {
    "Singapore University of Social Sciences": "Singapore University of Social Sciences",
    "Singapore Institute of Technology":       "Singapore Institute of Technology",
    "Singapore University of Technology and Design": "Singapore University of Technology and Design",
    "Nanyang Technological University":        "Nanyang Technological University",
    "National University of Singapore":        "National University of Singapore",
    "Singapore Management University":         "Singapore Management University",
}


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def normalize_degree(name: str) -> str:
    """
    Strip annotation suffixes and normalise spacing — but preserve original casing.
    Used to produce the clean display name stored in JSON.

    Strips: ###  ##  **  ^^  #  ^
    Then fixes spacing around parentheses.
    """
    for token in ("###", "##", "**", "^^", "#", "^"):
        name = name.replace(token, "")
    name = re.sub(r"  +", " ", name).strip()
    name = re.sub(r"\s*\(", " (", name)
    name = re.sub(r"\s+\)", ")", name)
    return name.strip()


def degree_key(name: str) -> str:
    """
    Lowercase grouping key used to merge rows that are the same course
    but differ in capitalisation or annotation markers across years.

    Examples that collapse to the same key:
        "Electrical And Electronic Engineering"
        "Electrical and Electronic Engineering"
        "Bachelor of Science (Pharmacy) #"
        "Bachelor of Science (Pharmacy)#**"
    """
    return normalize_degree(name).lower()


def slugify(text: str) -> str:
    """Convert any string to a safe filename slug."""
    text = str(text).strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)       # remove special chars
    text = re.sub(r"[\s_-]+", "_", text)        # spaces/underscores/hyphens → _
    text = re.sub(r"^-+|-+$", "", text)         # strip leading/trailing _
    return text[:120]                            # cap length for filesystem safety


def safe_float(val):
    """Return float or None — handles all the messy null representations in this CSV."""
    if val is None:
        return None
    s = str(val).strip().lower()
    if s in ("na", "n.a.", "n.a", "", "**", "nan", "none", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def round_or_none(val, decimals=1):
    """Return rounded float, or None for any missing-value representation.
    Catches Python None, float nan, float inf, and pandas NA/NaT.
    """
    if val is None:
        return None
    try:
        import math as _math
        f = float(val)
        if _math.isnan(f) or _math.isinf(f):
            return None
        return round(f, decimals)
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────
# STEP 1 — LOAD & CLEAN
# ─────────────────────────────────────────────

def load_and_clean(csv_path: str) -> pd.DataFrame:
    print(f"Loading {csv_path}...")
    df = pd.read_csv(csv_path, dtype=str)  # read everything as str first

    # Normalise column names
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # Strip whitespace from all string columns
    str_cols = df.select_dtypes(include="object").columns
    df[str_cols] = df[str_cols].apply(lambda c: c.str.strip())

    # Fix encoding artifacts in school names (e.g. TU München)
    df["school"] = df["school"].str.replace("Ã¤", "ä", regex=False)
    df["school"] = df["school"].str.replace("Ã¼", "ü", regex=False)
    df["school"] = df["school"].str.replace("Ã¶", "ö", regex=False)
    df["school"] = df["school"].str.replace("â€™", "'", regex=False)

    # Normalize "na" school values
    df["school"] = df["school"].replace({"na": None, "N.A.": None, "n.a.": None})

    # ── Normalise degree names & deduplicate ────────────────────
    # normalize_degree → cleans display name (strips markers, fixes spacing)
    # degree_key       → additionally lowercases for case-insensitive grouping
    #
    # This collapses variants like:
    #   "Electrical And Electronic Engineering"   (early years)
    #   "Electrical and Electronic Engineering"   (later years)
    #   "Bachelor of Science (Pharmacy) #"
    #   "Bachelor of Science (Pharmacy)#**"
    # into one canonical course with a continuous time series.
    before_count = df["degree"].nunique()
    df["degree_display"] = df["degree"].apply(normalize_degree)
    df["degree_key"]     = df["degree"].apply(degree_key)
    after_count = df["degree_key"].nunique()
    print(f"  Degree deduplication: {before_count} raw names → {after_count} canonical names "
          f"({before_count - after_count} collapsed)")

    # For the display name, pick the version from the latest available year
    # so the dropdown always shows the most up-to-date wording.
    latest_display = (
        df.sort_values("year")
          .groupby("degree_key")["degree_display"]
          .last()
          .rename("degree_display_final")
    )
    df = df.join(latest_display, on="degree_key")

    def first_non_null(s):
        non_null = s.dropna()
        return non_null.iloc[0] if len(non_null) > 0 else None

    key_cols = ["year", "university", "school", "degree_key"]
    agg_dict = {col: first_non_null for col in NUMERIC_COLS}
    agg_dict["degree_display_final"] = "first"

    before_rows = len(df)
    df = df.groupby(key_cols, dropna=False).agg(agg_dict).reset_index()
    after_rows = len(df)
    if before_rows != after_rows:
        print(f"  Row dedup: {before_rows} rows → {after_rows} rows "
              f"({before_rows - after_rows} duplicate rows merged)")

    # Replace raw degree column with the clean canonical display name
    df = df.rename(columns={"degree_display_final": "degree"})
    df = df.drop(columns=["degree_key"])

    # Cast numeric columns
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = df[col].apply(safe_float)

    # Cast year to int
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")

    # Drop rows where year or degree is missing (unusable)
    df = df.dropna(subset=["year", "degree"])

    # Normalize university names
    df["university"] = df["university"].map(
        lambda x: UNI_NORMALIZATIONS.get(x, x)
    )

    # Sort chronologically
    df = df.sort_values(["university", "degree", "year"]).reset_index(drop=True)

    print(f"  Loaded {len(df)} rows across {df['year'].nunique()} years "
          f"({int(df['year'].min())}–{int(df['year'].max())})")
    return df


# ─────────────────────────────────────────────
# STEP 2 — BUILD COURSE JSON FILES
# ─────────────────────────────────────────────

def build_course_files(df: pd.DataFrame, out_dir: Path) -> dict:
    """
    One JSON file per (university, degree) combination.
    Returns the slug→metadata index dict.
    """
    courses_dir = out_dir / "courses"
    courses_dir.mkdir(parents=True, exist_ok=True)

    course_index = {}   # slug -> {university, school, degree, slug}
    slug_collision_counter = {}

    groups = df.groupby(["university", "degree"], sort=True)
    print(f"\nWriting {len(groups)} course JSON files...")

    for (uni, degree), group in groups:
        group = group.sort_values("year")

        # Determine the most common school name for this degree across years
        # (some degrees move between schools over time — we pick the latest)
        school = group["school"].dropna().iloc[-1] if group["school"].dropna().shape[0] > 0 else None

        # Build the base slug
        base_slug = slugify(f"{uni}_{degree}")

        # Handle rare slug collisions
        if base_slug in slug_collision_counter:
            slug_collision_counter[base_slug] += 1
            slug = f"{base_slug}_{slug_collision_counter[base_slug]}"
        else:
            slug_collision_counter[base_slug] = 0
            slug = base_slug

        # ── Build yearly data rows ──────────────────────────
        yearly_data = []
        for _, row in group.iterrows():
            year_entry = {"year": int(row["year"])}
            for col in NUMERIC_COLS:
                year_entry[col] = round_or_none(row.get(col))
            yearly_data.append(year_entry)

        # ── Drop years where every numeric field is null ─────
        # These are "**" suppressed cohorts in the raw CSV (small
        # sample size, no data published). Keeping them create
        # gaps in charts and make latest_year show N/A even when
        # earlier years have real data.
        # Note: round_or_none converts nan/inf → None, so checking
        # "is not None" here is sufficient after that conversion.
        yearly_data = [
            row for row in yearly_data
            if any(row[col] is not None for col in NUMERIC_COLS)
        ]

        # Skip this course entirely if it has no usable data at all
        # (e.g. a degree that only ever appeared as "**" rows)
        if not yearly_data:
            continue

        # ── Latest year snapshot (from cleaned data) ─────────
        # Use the last entry in yearly_data (not group.iloc[-1])
        # so latest_year reflects the most recent year with real data.
        latest_year_data = dict(yearly_data[-1])  # already has year + all numeric cols

        # ── Compute simple stats (ignoring None) ─────────────
        def series_values(col):
            return [r[col] for r in yearly_data if r[col] is not None]

        salary_vals = series_values("gross_monthly_median")
        emp_vals    = series_values("employment_rate_ft_perm")

        stats = {}
        if salary_vals:
            stats["salary_min"]   = round(min(salary_vals), 1)
            stats["salary_max"]   = round(max(salary_vals), 1)
            stats["salary_latest"] = salary_vals[-1]
            # % change from first to last available data point
            if len(salary_vals) >= 2:
                stats["salary_change_pct"] = round(
                    (salary_vals[-1] - salary_vals[0]) / salary_vals[0] * 100, 1
                )
        if emp_vals:
            stats["emp_latest"] = emp_vals[-1]

        # ── Assemble payload ─────────────────────────────────
        payload = {
            "slug":        slug,
            "university":  uni,
            "school":      school,
            "degree":      degree,
            "years_available": [int(r["year"]) for r in yearly_data],
            "latest_year": latest_year_data["year"],
            "latest":      latest_year_data,
            "stats":       stats,
            "metric_labels": METRIC_LABELS,
            "data":        yearly_data,   # full time series, all metrics
        }

        filepath = courses_dir / f"{slug}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, separators=(",", ":"), cls=SafeJSONEncoder)   # minified

        # Add to index
        course_index[slug] = {
            "slug":       slug,
            "university": uni,
            "school":     school,
            "degree":     degree,
            "latest_year": latest_year_data["year"],
            "latest_gross_monthly_median":   latest_year_data.get("gross_monthly_median"),
            "latest_employment_rate_ft_perm": latest_year_data.get("employment_rate_ft_perm"),
            "years_available": [int(r["year"]) for r in yearly_data],
        }

    # Write course index
    index_path = courses_dir / "index.json"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(course_index, f, separators=(",", ":"), cls=SafeJSONEncoder)
    print(f"  Written course index → {index_path}")

    return course_index


# ─────────────────────────────────────────────
# STEP 3 — BUILD METADATA (for dropdowns)
# ─────────────────────────────────────────────

def build_metadata(df: pd.DataFrame, course_index: dict, out_dir: Path):
    """
    metadata.json drives all the dropdown filter logic on the frontend.

    Structure:
    {
      "universities": ["NTU", "NUS", ...],
      "years": [2013, 2014, ...],
      "metrics": { col: label, ... },
      "tree": {
        "NTU": {
          "College of Engineering": {
            "Computer Science": "ntu_computer_science",   <- slug
            ...
          }
        }
      },
      "flat": [
        { "university": "NTU", "school": "...", "degree": "...", "slug": "..." },
        ...
      ]
    }
    """
    print("\nBuilding metadata.json...")

    universities = sorted(df["university"].dropna().unique().tolist())
    years        = sorted(df["year"].dropna().astype(int).unique().tolist())

    # Build tree: uni → school → degree → slug
    tree = {}
    for slug, meta in course_index.items():
        uni    = meta["university"]
        school = meta["school"] or "Other"
        degree = meta["degree"]

        tree.setdefault(uni, {})
        tree[uni].setdefault(school, {})
        tree[uni][school][degree] = slug

    # Sort everything alphabetically for clean UX
    tree_sorted = {
        uni: {
            school: dict(sorted(degrees.items()))
            for school, degrees in sorted(schools.items())
        }
        for uni, schools in sorted(tree.items())
    }

    # Flat list (useful for search/autocomplete)
    flat = sorted(
        list(course_index.values()),
        key=lambda x: (x["university"], x["school"] or "", x["degree"])
    )

    metadata = {
        "universities": universities,
        "years":        years,
        "metrics":      METRIC_LABELS,
        "tree":         tree_sorted,
        "flat":         flat,
        "generated_at": pd.Timestamp.now().isoformat(),
        "total_courses": len(course_index),
    }

    meta_path = out_dir / "metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, cls=SafeJSONEncoder)   # pretty-printed (loaded once, worth readability)

    print(f"  Written metadata → {meta_path}")
    print(f"  {len(universities)} universities | {len(years)} years | {len(course_index)} courses")

    return metadata


# ─────────────────────────────────────────────
# STEP 4 — SANITY CHECK
# ─────────────────────────────────────────────

def sanity_check(out_dir: Path, course_index: dict):
    print("\nSanity check...")
    courses_dir = out_dir / "courses"

    # Check all slugs in the index actually have a file
    missing = []
    for slug in course_index:
        if not (courses_dir / f"{slug}.json").exists():
            missing.append(slug)

    if missing:
        print(f"  ⚠ WARNING: {len(missing)} slugs in index have no file: {missing[:5]}")
    else:
        print(f"  ✓ All {len(course_index)} course files verified")

    # Check metadata file
    meta_path = out_dir / "metadata.json"
    if meta_path.exists():
        size_kb = meta_path.stat().st_size / 1024
        print(f"  ✓ metadata.json exists ({size_kb:.1f} KB)")
    else:
        print("  ✗ metadata.json MISSING")

    # Sample a course file and print it
    sample_slug = next(iter(course_index))
    sample_path = courses_dir / f"{sample_slug}.json"
    with open(sample_path) as f:
        sample = json.load(f)
    print(f"\n  Sample course: {sample['university']} — {sample['degree']}")
    print(f"    Years: {sample['years_available']}")
    print(f"    Latest year: {sample['latest_year']}")
    print(f"    Latest gross median: {sample['latest'].get('gross_monthly_median')}")
    print(f"    Stats: {sample['stats']}")


# ─────────────────────────────────────────────
# STEP 5 — PRINT SUMMARY TABLE
# ─────────────────────────────────────────────

def print_summary(df: pd.DataFrame):
    print("\n── Courses per university ──────────────────────────")
    summary = (
        df.groupby("university")["degree"]
        .nunique()
        .sort_values(ascending=False)
        .reset_index()
    )
    summary.columns = ["University", "Unique Degrees"]
    print(summary.to_string(index=False))

    print("\n── Year coverage ────────────────────────────────────")
    year_counts = df.groupby("year").size().reset_index(name="Rows")
    print(year_counts.to_string(index=False))

    print("\n── Null rate per numeric column ─────────────────────")
    for col in NUMERIC_COLS:
        if col in df.columns:
            null_pct = df[col].isna().mean() * 100
            print(f"  {col:<40} {null_pct:5.1f}% null")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Graduate Employment Survey — Static Site Builder")
    print("=" * 60)

    # Create output dirs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "courses").mkdir(parents=True, exist_ok=True)

    # Run pipeline
    df            = load_and_clean(INPUT_CSV)
    print_summary(df)
    course_index  = build_course_files(df, OUTPUT_DIR)
    metadata      = build_metadata(df, course_index, OUTPUT_DIR)
    sanity_check(OUTPUT_DIR, course_index)

    # Print file size summary
    total_size = sum(
        f.stat().st_size
        for f in OUTPUT_DIR.rglob("*.json")
    )
    file_count = sum(1 for _ in OUTPUT_DIR.rglob("*.json"))
    print(f"\n── Output summary ───────────────────────────────────")
    print(f"  {file_count} JSON files")
    print(f"  {total_size / 1024:.1f} KB total ({total_size / 1024 / 1024:.2f} MB)")
    print(f"\n✓ Done. Commit the docs/ folder to GitHub and enable GitHub Pages.")
    print(f"  GitHub Pages setting: Source = 'docs/' folder on main branch")


if __name__ == "__main__":
    main()
