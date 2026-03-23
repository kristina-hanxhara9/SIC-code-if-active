"""
Standalone batch search script — no Streamlit required.

Usage:
    python batch_search.py companies.xlsx

Reads company names from column A and postcodes from column B,
searches Companies House, and writes results to companies_house_results.xlsx.
"""

import os
import sys
import time

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("COMPANIES_HOUSE_API_KEY", "")
BASE_URL = "https://api.company-information.service.gov.uk"

# Import SIC_DESCRIPTIONS from app.py
from app import SIC_DESCRIPTIONS


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


def matches_postcode(company_data, postcode):
    if not postcode:
        return True
    addr = company_data.get("address", {}) or company_data.get("registered_office_address", {})
    company_postcode = (addr.get("postal_code", "") or "").replace(" ", "").upper()
    search_postcode = postcode.replace(" ", "").upper()
    return search_postcode in company_postcode or company_postcode in search_postcode


def is_northern_ireland(addr):
    if not addr:
        return False
    country = (addr.get("country", "") or "").upper()
    region = (addr.get("region", "") or "").upper()
    postcode = (addr.get("postal_code", "") or "").replace(" ", "").upper()
    return "NORTHERN IRELAND" in country or "NORTHERN IRELAND" in region or postcode.startswith("BT")


def main():
    input_file = sys.argv[1] if len(sys.argv) > 1 else "companies.xlsx"
    output_file = "companies_house_results.xlsx"

    if not API_KEY or API_KEY == "your_api_key_here":
        print("ERROR: Set COMPANIES_HOUSE_API_KEY in your .env file.")
        sys.exit(1)

    print(f"Reading {input_file}...")
    df = pd.read_excel(input_file)

    # Use first column as name, second column as postcode
    cols = df.columns.tolist()
    name_col = cols[0]
    pc_col = cols[1] if len(cols) > 1 else None

    print(f"  Name column: {name_col}")
    print(f"  Postcode column: {pc_col or '(none)'}")

    names = df[name_col].astype(str).str.strip()
    postcodes = df[pc_col].fillna("").astype(str).str.strip() if pc_col else pd.Series([""] * len(df))

    # Build unique pairs
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
                print(f"    Rate limited, waiting 5s...")
                time.sleep(5)
                try:
                    results = search_companies(name)
                except Exception:
                    export_rows.append({"Search Name": name, "Search Postcode": pc, "Error": "Rate limited"})
                    print(f"    FAILED after retry")
                    continue
            else:
                export_rows.append({"Search Name": name, "Search Postcode": pc, "Error": f"HTTP {e.response.status_code}"})
                print(f"    API error: {e.response.status_code}")
                continue
        except requests.exceptions.RequestException as e:
            export_rows.append({"Search Name": name, "Search Postcode": pc, "Error": str(e)})
            print(f"    Request failed: {e}")
            continue

        items = results.get("items", [])
        if not items:
            export_rows.append({"Search Name": name, "Search Postcode": pc, "Error": "No results"})
            print(f"    No results")
            continue

        # Filter by postcode
        postcode_matched = True
        if pc:
            matched = [item for item in items if matches_postcode(item, pc)]
            if not matched:
                matched = items[:1]
                postcode_matched = False
                print(f"    No postcode match, using top result")
            items = matched

        # Chain detection
        active_items = [
            item for item in results.get("items", [])
            if item.get("company_status", "").lower() == "active"
            and item.get("title", "").upper() == name.upper()
        ]
        is_chain = len(active_items) > 1

        top = items[0]
        company_number = top.get("company_number", "")
        title = top.get("title", "Unknown")
        status = top.get("company_status", "unknown")

        # Fetch full profile
        profile = None
        try:
            profile = get_company_profile(company_number)
        except requests.exceptions.RequestException as e:
            print(f"    Could not load profile: {e}")

        sic_codes = profile.get("sic_codes", []) if profile else []
        sic_descriptions = [SIC_DESCRIPTIONS.get(c, "Unknown") for c in sic_codes]
        reg_addr = profile.get("registered_office_address", {}) if profile else {}

        export_rows.append({
            "Search Name": name,
            "Search Postcode": pc,
            "Company Name": title,
            "Company Number": company_number,
            "Status": status.upper(),
            "Postcode Match": "Yes" if postcode_matched else "No",
            "Chain": "Yes" if is_chain else "No",
            "Chain Locations": len(active_items) if is_chain else "",
            "SIC Codes": ", ".join(sic_codes),
            "SIC Descriptions": ", ".join(sic_descriptions),
            "Registered Address": format_address(reg_addr),
            "Northern Ireland": "Yes" if is_northern_ireland(reg_addr) else "No",
        })

        print(f"    -> {title} ({status.upper()}) SIC: {', '.join(sic_codes) or 'none'}")
        time.sleep(0.3)

    # Write output
    export_df = pd.DataFrame(export_rows)
    export_df.to_excel(output_file, index=False, engine="openpyxl")
    print(f"\nDone! Results saved to {output_file} ({len(export_rows)} rows)")


if __name__ == "__main__":
    main()
