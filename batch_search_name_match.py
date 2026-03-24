"""
Batch search with name-match fallback.

When postcode doesn't match, falls back to name matching instead of
taking the first result. Shows what was found, the new address/postcode,
status, company numbers, and SIC codes.

Reads from the ORIGINAL Excel file (not results).

Usage:
    python batch_search_name_match.py companies.xlsx
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

# Load full SIC descriptions from CSV
SIC_DESCRIPTIONS = {}
csv_path = os.path.join(os.path.dirname(__file__), "sic_codes_full.csv")
if os.path.exists(csv_path):
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row["sic_code"].strip()
            desc = row["sic_description"].strip()
            padded = code.zfill(5)
            SIC_DESCRIPTIONS[padded] = desc
            SIC_DESCRIPTIONS[code] = desc


def sic_description(code):
    code = str(code).strip()
    if code in SIC_DESCRIPTIONS:
        return SIC_DESCRIPTIONS[code]
    padded = code.zfill(5)
    if padded in SIC_DESCRIPTIONS:
        return SIC_DESCRIPTIONS[padded]
    stripped = code.lstrip("0")
    if stripped in SIC_DESCRIPTIONS:
        return SIC_DESCRIPTIONS[stripped]
    return f"SIC {code}"


def search_companies(query):
    resp = requests.get(
        f"{BASE_URL}/search/companies",
        params={"q": query, "items_per_page": 20},
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


def get_postcode(addr):
    if not addr:
        return ""
    return (addr.get("postal_code", "") or "").strip()


def matches_postcode(company_data, postcode):
    if not postcode:
        return True
    addr = company_data.get("address", {}) or company_data.get("registered_office_address", {})
    company_postcode = (addr.get("postal_code", "") or "").replace(" ", "").upper()
    search_postcode = postcode.replace(" ", "").upper()
    return search_postcode in company_postcode or company_postcode in search_postcode


def normalise_name(name):
    name = name.upper().strip()
    for suffix in ["LIMITED", "LTD", "PLC", "LLP", "LP", "INC", "INCORPORATED",
                   "& CO", "AND CO", "& COMPANY", "AND COMPANY"]:
        name = name.replace(suffix, "")
    name = re.sub(r"[^A-Z0-9 ]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def names_match(search_name, company_name):
    a = normalise_name(search_name)
    b = normalise_name(company_name)
    if a == b:
        return True
    if a in b or b in a:
        return True
    return False


def is_northern_ireland(addr):
    if not addr:
        return False
    country = (addr.get("country", "") or "").upper()
    region = (addr.get("region", "") or "").upper()
    postcode = (addr.get("postal_code", "") or "").replace(" ", "").upper()
    return "NORTHERN IRELAND" in country or "NORTHERN IRELAND" in region or postcode.startswith("BT")


def main():
    input_file = sys.argv[1] if len(sys.argv) > 1 else "companies.xlsx"
    output_file = "companies_house_results_name_match.xlsx"

    if not API_KEY or API_KEY == "your_api_key_here":
        print("ERROR: Set COMPANIES_HOUSE_API_KEY in your .env file.")
        sys.exit(1)

    print(f"Reading {input_file}...")
    df = pd.read_excel(input_file)

    cols = df.columns.tolist()
    name_col = cols[0]
    pc_col = cols[1] if len(cols) > 1 else None

    print(f"  Name column: {name_col}")
    print(f"  Postcode column: {pc_col or '(none)'}")

    names = df[name_col].astype(str).str.strip()
    postcodes = df[pc_col].fillna("").astype(str).str.strip() if pc_col else pd.Series([""] * len(df))

    pairs_df = pd.DataFrame({"name": names, "pc": postcodes})
    pairs_df = pairs_df[(pairs_df["name"] != "") & (pairs_df["name"] != "nan")]
    pairs = pairs_df.drop_duplicates().values.tolist()

    print(f"Searching {len(pairs)} companies...\n")

    export_rows = []

    for i, (name, pc) in enumerate(pairs):
        print(f"  [{i+1}/{len(pairs)}] {name}" + (f" ({pc})" if pc else ""))

        # Search
        try:
            results = search_companies(name)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                print("    Rate limited, waiting 5s...")
                time.sleep(5)
                try:
                    results = search_companies(name)
                except Exception:
                    export_rows.append({
                        "Search Name": name, "Search Postcode": pc,
                        "Match Type": "ERROR", "Error": "Rate limited",
                    })
                    print("    FAILED after retry")
                    continue
            else:
                export_rows.append({
                    "Search Name": name, "Search Postcode": pc,
                    "Match Type": "ERROR", "Error": f"HTTP {e.response.status_code}",
                })
                print(f"    API error: {e.response.status_code}")
                continue
        except requests.exceptions.RequestException as e:
            export_rows.append({
                "Search Name": name, "Search Postcode": pc,
                "Match Type": "ERROR", "Error": str(e),
            })
            print(f"    Request failed: {e}")
            continue

        items = results.get("items", [])
        if not items:
            export_rows.append({
                "Search Name": name, "Search Postcode": pc,
                "Match Type": "NO RESULTS", "Error": "No results found",
            })
            print("    No results")
            continue

        # --- Matching logic ---
        # Priority 1: Postcode + Name match
        # Priority 2: Postcode only
        # Priority 3: Name match (the key fallback)
        # Priority 4: No match
        match_type = None
        chosen = None

        if pc:
            postcode_matches = [item for item in items if matches_postcode(item, pc)]
            # Among postcode matches, prefer name match
            for item in postcode_matches:
                if names_match(name, item.get("title", "")):
                    chosen = item
                    match_type = "POSTCODE + NAME"
                    break
            # Postcode match but no name match
            if not chosen and postcode_matches:
                chosen = postcode_matches[0]
                match_type = "POSTCODE ONLY"

        # Fallback: name match (instead of taking first result)
        if not chosen:
            for item in items:
                if names_match(name, item.get("title", "")):
                    chosen = item
                    match_type = "NAME ONLY"
                    break

        # No match at all
        if not chosen:
            export_rows.append({
                "Search Name": name,
                "Search Postcode": pc,
                "Match Type": "NO MATCH",
                "Error": "No name or postcode match found",
            })
            print(f"    NO MATCH — none of the results matched")
            continue

        company_number = chosen.get("company_number", "")
        title = chosen.get("title", "Unknown")
        status = chosen.get("company_status", "unknown")

        print(f"    -> {title} ({status.upper()}) [{match_type}]")

        # Chain detection
        active_items = [
            item for item in items
            if item.get("company_status", "").lower() == "active"
            and names_match(name, item.get("title", ""))
        ]
        is_chain = len(active_items) > 1

        # Fetch full profile for SIC codes and registered address
        profile = None
        try:
            profile = get_company_profile(company_number)
        except requests.exceptions.RequestException as e:
            print(f"    Could not load profile: {e}")

        sic_codes = profile.get("sic_codes", []) if profile else []
        sic_descs = [sic_description(c) for c in sic_codes]
        reg_addr = profile.get("registered_office_address", {}) if profile else {}
        found_postcode = get_postcode(reg_addr)
        found_address = format_address(reg_addr)

        row = {
            "Search Name": name,
            "Search Postcode": pc,
            "Match Type": match_type,
            "Company Name Found": title,
            "Company Number": company_number,
            "Status": status.upper(),
            "Found Postcode": found_postcode,
            "Found Address": found_address,
            "SIC Codes": ", ".join(sic_codes),
            "SIC Descriptions": ", ".join(sic_descs),
            "Chain": "Yes" if is_chain else "No",
            "Chain Locations": len(active_items) if is_chain else "",
            "Northern Ireland": "Yes" if is_northern_ireland(reg_addr) else "No",
        }

        export_rows.append(row)
        time.sleep(0.3)

    # Write output
    export_df = pd.DataFrame(export_rows)

    # Order columns
    desired_cols = [
        "Search Name", "Search Postcode", "Match Type",
        "Company Name Found", "Company Number", "Status",
        "Found Postcode", "Found Address",
        "SIC Codes", "SIC Descriptions",
        "Chain", "Chain Locations", "Northern Ireland", "Error",
    ]
    cols = [c for c in desired_cols if c in export_df.columns]
    extra = [c for c in export_df.columns if c not in desired_cols]
    export_df = export_df[cols + extra]

    export_df.to_excel(output_file, index=False, engine="openpyxl")

    # Summary
    total = len(export_df)
    match_counts = export_df["Match Type"].value_counts().to_dict() if "Match Type" in export_df.columns else {}
    print(f"\nDone! Saved {output_file} ({total} rows)")
    for mt, count in match_counts.items():
        print(f"  {mt}: {count}")


if __name__ == "__main__":
    main()
