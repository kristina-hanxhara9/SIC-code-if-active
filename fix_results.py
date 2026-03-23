"""
Re-search script: reads the existing results file and fixes problem rows.

- Loads SIC descriptions from the full Companies House condensed CSV (731 codes)
- Re-searches rows where:
    * Match Type is "NO MATCH", "NO RESULTS", or "ERROR"
    * SIC Descriptions contain "Unknown"
    * Match Type is "POSTCODE ONLY" (name didn't match — retry by name)
- Uses relaxed name matching (fuzzy)
- Reports match type: "Postcode Match", "Name Match", or "Error"

Usage:
    python fix_results.py [results_file.xlsx]

Defaults to companies_house_results_strict.xlsx
Outputs: companies_house_results_fixed.xlsx
"""

import csv
import os
import re
import sys
import time

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("COMPANIES_HOUSE_API_KEY", "")
BASE_URL = "https://api.company-information.service.gov.uk"

# ---------------------------------------------------------------------------
# Load full SIC descriptions from CSV (731 codes)
# ---------------------------------------------------------------------------
SIC_DESCRIPTIONS = {}
csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sic_codes_full.csv")
if os.path.exists(csv_path):
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row["sic_code"].strip()
            desc = row["sic_description"].strip()
            # API returns 5-digit codes with leading zeros; CSV may not
            padded = code.zfill(5)
            SIC_DESCRIPTIONS[padded] = desc
            SIC_DESCRIPTIONS[code] = desc  # keep both forms
    print(f"Loaded {len(SIC_DESCRIPTIONS)} SIC descriptions from CSV")
else:
    print(f"WARNING: {csv_path} not found — SIC descriptions will be empty")


def sic_description(code):
    """Look up a SIC code description, never returns 'Unknown'."""
    code = str(code).strip()
    if code in SIC_DESCRIPTIONS:
        return SIC_DESCRIPTIONS[code]
    padded = code.zfill(5)
    if padded in SIC_DESCRIPTIONS:
        return SIC_DESCRIPTIONS[padded]
    # Try without leading zeros
    stripped = code.lstrip("0")
    if stripped in SIC_DESCRIPTIONS:
        return SIC_DESCRIPTIONS[stripped]
    return f"SIC {code}"


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------
def search_companies(query, items_per_page=20):
    resp = requests.get(
        f"{BASE_URL}/search/companies",
        params={"q": query, "items_per_page": items_per_page},
        auth=(API_KEY, ""),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_company_profile(company_number):
    resp = requests.get(
        f"{BASE_URL}/company/{company_number}",
        auth=(API_KEY, ""),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def format_address(addr):
    if not addr:
        return "N/A"
    parts = [
        addr.get("premises", ""),
        addr.get("address_line_1", ""),
        addr.get("address_line_2", ""),
        addr.get("locality", ""),
        addr.get("region", ""),
        addr.get("postal_code", ""),
        addr.get("country", ""),
    ]
    return ", ".join(p for p in parts if p)


def is_northern_ireland(addr):
    if not addr:
        return False
    country = (addr.get("country", "") or "").upper()
    region = (addr.get("region", "") or "").upper()
    postcode = (addr.get("postal_code", "") or "").replace(" ", "").upper()
    return "NORTHERN IRELAND" in country or "NORTHERN IRELAND" in region or postcode.startswith("BT")


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------
def normalise(name):
    name = name.upper().strip()
    for suffix in [
        "LIMITED", "LTD", "PLC", "LLP", "LP", "INC", "INCORPORATED",
        "& CO", "AND CO", "& COMPANY", "AND COMPANY", "UK", "U.K.",
        "HOLDINGS", "GROUP", "SERVICES", "THE",
    ]:
        name = name.replace(suffix, "")
    name = re.sub(r"[^A-Z0-9 ]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def name_similarity(a, b):
    """Simple word-overlap similarity between 0 and 1."""
    wa = set(normalise(a).split())
    wb = set(normalise(b).split())
    if not wa or not wb:
        return 0.0
    overlap = wa & wb
    return len(overlap) / max(len(wa), len(wb))


def names_match(search_name, company_name, threshold=0.5):
    """Relaxed name match — at least 50% word overlap after normalisation."""
    a = normalise(search_name)
    b = normalise(company_name)
    if not a or not b:
        return False
    if a == b:
        return True
    if a in b or b in a:
        return True
    return name_similarity(search_name, company_name) >= threshold


def matches_postcode(data, postcode):
    if not postcode:
        return False
    addr = data.get("address", {}) or data.get("registered_office_address", {})
    cp = (addr.get("postal_code", "") or "").replace(" ", "").upper()
    sp = postcode.replace(" ", "").upper()
    return sp and cp and (sp in cp or cp in sp)


# ---------------------------------------------------------------------------
# Build a result row from a matched company
# ---------------------------------------------------------------------------
def build_row(name, pc, chosen, match_type, items):
    company_number = chosen.get("company_number", "")
    title = chosen.get("title", "Unknown")
    status = chosen.get("company_status", "unknown")

    # Chain detection
    active_matches = [
        item for item in items
        if item.get("company_status", "").lower() == "active"
        and names_match(name, item.get("title", ""))
    ]
    is_chain = len(active_matches) > 1

    # Fetch full profile for SIC codes
    profile = None
    try:
        profile = get_company_profile(company_number)
    except requests.exceptions.RequestException as e:
        print(f"      Could not load profile: {e}")

    sic_codes = profile.get("sic_codes", []) if profile else []
    sic_descs = [sic_description(c) for c in sic_codes]
    reg_addr = profile.get("registered_office_address", {}) if profile else {}

    return {
        "Search Name": name,
        "Search Postcode": pc,
        "Company Name": title,
        "Company Number": company_number,
        "Status": status.upper(),
        "Postcode Match": "Yes" if matches_postcode(chosen, pc) else "No",
        "Name Match": "Yes" if names_match(name, title) else "No",
        "Match Type": match_type,
        "Chain": "Yes" if is_chain else "No",
        "Chain Locations": len(active_matches) if is_chain else "",
        "SIC Codes": ", ".join(sic_codes),
        "SIC Descriptions": ", ".join(sic_descs),
        "Registered Address": format_address(reg_addr),
        "Northern Ireland": "Yes" if is_northern_ireland(reg_addr) else "No",
    }


# ---------------------------------------------------------------------------
# Determine which rows need re-searching
# ---------------------------------------------------------------------------
def needs_fix(row):
    mt = str(row.get("Match Type", "")).upper()
    sic_desc = str(row.get("SIC Descriptions", ""))
    # Re-search if: no match, error, unknown SIC, or only postcode matched (not name)
    if mt in ("NO MATCH", "NO RESULTS", "ERROR"):
        return True
    if "Unknown" in sic_desc or "unknown" in sic_desc:
        return True
    if mt == "POSTCODE ONLY":
        return True
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    input_file = sys.argv[1] if len(sys.argv) > 1 else "companies_house_results_strict.xlsx"
    output_file = "companies_house_results_fixed.xlsx"

    if not API_KEY or API_KEY == "your_api_key_here":
        print("ERROR: Set COMPANIES_HOUSE_API_KEY in your .env file.")
        sys.exit(1)

    print(f"Reading {input_file}...")
    df = pd.read_excel(input_file)
    print(f"  {len(df)} total rows")

    to_fix = df[df.apply(needs_fix, axis=1)]
    already_good = df[~df.apply(needs_fix, axis=1)]
    print(f"  {len(to_fix)} rows need fixing")
    print(f"  {len(already_good)} rows already good")

    # Re-build the good rows with updated SIC descriptions from the full CSV
    good_rows = []
    for _, row in already_good.iterrows():
        r = row.to_dict()
        # Fix SIC descriptions using full CSV
        sic_codes_str = str(r.get("SIC Codes", ""))
        if sic_codes_str and sic_codes_str != "nan":
            codes = [c.strip() for c in sic_codes_str.split(",") if c.strip()]
            r["SIC Descriptions"] = ", ".join(sic_description(c) for c in codes)
        # Add Postcode Match / Name Match columns if missing
        if "Postcode Match" not in r:
            mt = str(r.get("Match Type", "")).upper()
            r["Postcode Match"] = "Yes" if "POSTCODE" in mt else "No"
            r["Name Match"] = "Yes" if "NAME" in mt else "No"
        good_rows.append(r)

    # Re-search the problem rows
    fix_rows = []
    for idx, (_, row) in enumerate(to_fix.iterrows()):
        name = str(row.get("Search Name", "")).strip()
        pc = str(row.get("Search Postcode", "")).strip()
        if pc == "nan":
            pc = ""

        print(f"\n  [{idx+1}/{len(to_fix)}] Re-searching: {name}" + (f" ({pc})" if pc else ""))

        try:
            results = search_companies(name)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                print("    Rate limited, waiting 5s...")
                time.sleep(5)
                try:
                    results = search_companies(name)
                except Exception:
                    fix_rows.append({
                        "Search Name": name, "Search Postcode": pc,
                        "Match Type": "Error", "SIC Descriptions": "Rate limited",
                    })
                    continue
            else:
                fix_rows.append({
                    "Search Name": name, "Search Postcode": pc,
                    "Match Type": "Error", "SIC Descriptions": f"HTTP {e.response.status_code}",
                })
                continue
        except Exception as e:
            fix_rows.append({
                "Search Name": name, "Search Postcode": pc,
                "Match Type": "Error", "SIC Descriptions": str(e),
            })
            continue

        items = results.get("items", [])
        if not items:
            fix_rows.append({
                "Search Name": name, "Search Postcode": pc,
                "Match Type": "Error", "SIC Descriptions": "No results from API",
            })
            print("    No results")
            continue

        chosen = None
        match_type = None

        # Priority 1: Postcode + name match
        if pc:
            for item in items:
                if matches_postcode(item, pc) and names_match(name, item.get("title", "")):
                    chosen = item
                    match_type = "Postcode Match, Name Match"
                    break

        # Priority 2: Postcode match (any)
        if not chosen and pc:
            for item in items:
                if matches_postcode(item, pc):
                    chosen = item
                    match_type = "Postcode Match"
                    break

        # Priority 3: Name match (ignore postcode entirely)
        if not chosen:
            best_item = None
            best_score = 0.0
            for item in items:
                title = item.get("title", "")
                score = name_similarity(name, title)
                # Also boost exact substring matches
                if normalise(name) in normalise(title) or normalise(title) in normalise(name):
                    score = max(score, 0.8)
                if score > best_score:
                    best_score = score
                    best_item = item

            if best_item and best_score >= 0.5:
                chosen = best_item
                match_type = "Name Match"

        # Nothing matched at all → Error
        if not chosen:
            fix_rows.append({
                "Search Name": name, "Search Postcode": pc,
                "Match Type": "Error",
                "Postcode Match": "No",
                "Name Match": "No",
                "SIC Descriptions": "No matching company found",
            })
            print(f"    ERROR — no match found")
            continue

        print(f"    -> {chosen.get('title', '?')} [{match_type}]")
        row_data = build_row(name, pc, chosen, match_type, items)
        fix_rows.append(row_data)
        time.sleep(0.3)

    # Combine and output
    all_rows = good_rows + fix_rows
    out_df = pd.DataFrame(all_rows)

    # Reorder columns
    desired_cols = [
        "Search Name", "Search Postcode", "Company Name", "Company Number",
        "Status", "Postcode Match", "Name Match", "Match Type",
        "Chain", "Chain Locations", "SIC Codes", "SIC Descriptions",
        "Registered Address", "Northern Ireland",
    ]
    cols = [c for c in desired_cols if c in out_df.columns]
    extra = [c for c in out_df.columns if c not in desired_cols]
    out_df = out_df[cols + extra]

    out_df.to_excel(output_file, index=False, engine="openpyxl")

    # Summary
    error_count = len(out_df[out_df["Match Type"] == "Error"]) if "Match Type" in out_df.columns else 0
    print(f"\nDone! Saved {output_file} ({len(out_df)} rows, {error_count} errors)")


if __name__ == "__main__":
    main()
