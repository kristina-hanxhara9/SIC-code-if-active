"""
Fuzzy match checker for NO MATCH rows.

Reads companies_house_results_name_match.xlsx, finds rows where
Error = "No name or postcode match found", compares column O
(user-provided names) against column A (Search Name) using fuzzy
matching, and writes column P with "Yes Fuzzy Match" or "No Fuzzy Match".

Usage:
    python fuzzy_check.py
    python fuzzy_check.py companies_house_results_name_match.xlsx
"""

import re
import sys

import pandas as pd


def normalise(name):
    """Normalise a name for fuzzy comparison."""
    name = str(name).upper().strip()
    # Replace & with AND
    name = name.replace("&", "AND")
    # Remove common suffixes
    for suffix in ["LIMITED", "LTD", "PLC", "LLP", "LP", "INC", "INCORPORATED",
                   "& CO", "AND CO", "& COMPANY", "AND COMPANY",
                   "THE", "UK", "GROUP"]:
        name = re.sub(r'\b' + re.escape(suffix) + r'\b', '', name)
    # Remove punctuation, keep only letters, numbers, spaces
    name = re.sub(r"[^A-Z0-9 ]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def get_words(name):
    """Get the set of meaningful words from a normalised name."""
    return set(normalise(name).split())


def fuzzy_match(search_name, alt_name):
    """
    Check if two company names are a fuzzy match.

    Handles:
    - Spaces / punctuation differences
    - & vs AND
    - Common suffixes (LTD, LIMITED, etc.)
    - One name being a subset of the other (e.g. "Philips Auto Centre"
      vs "Philips Auto Service Centre")
    - Word overlap >= 60%
    """
    a = normalise(search_name)
    b = normalise(alt_name)

    # Exact match after normalisation
    if a == b:
        return True

    # One contains the other as a substring
    if a in b or b in a:
        return True

    # Word-level matching
    words_a = get_words(search_name)
    words_b = get_words(alt_name)

    if not words_a or not words_b:
        return False

    common = words_a & words_b
    # All words from the shorter name appear in the longer one
    shorter = min(words_a, words_b, key=len)
    if shorter and shorter.issubset(words_a) and shorter.issubset(words_b):
        return True

    # At least 60% word overlap relative to the shorter name
    overlap = len(common) / len(shorter) if shorter else 0
    if overlap >= 0.6:
        return True

    return False


def main():
    input_file = sys.argv[1] if len(sys.argv) > 1 else "companies_house_results_name_match.xlsx"

    print(f"Reading {input_file}...")
    df = pd.read_excel(input_file)

    print(f"  {len(df)} rows, {len(df.columns)} columns")
    print(f"  Columns: {list(df.columns)}")

    # Find the Error column and the user-added column O
    if "Error" not in df.columns:
        print("ERROR: No 'Error' column found.")
        sys.exit(1)

    col_names = df.columns.tolist()
    if len(col_names) < 15:
        print(f"ERROR: Expected at least 15 columns (O column), found {len(col_names)}.")
        print("Make sure you've added company names in column O.")
        sys.exit(1)

    search_col = col_names[0]  # Column A = Search Name
    alt_col = col_names[14]    # Column O = user-provided alternative names
    print(f"  Column A (Search Name): '{search_col}'")
    print(f"  Column O (Alt Names):   '{alt_col}'")

    # Add column P
    fuzzy_results = []
    match_count = 0
    no_match_count = 0
    checked = 0

    for idx, row in df.iterrows():
        error_val = str(row.get("Error", "")).strip()
        if error_val != "No name or postcode match found":
            fuzzy_results.append("")
            continue

        search_name = str(row.iloc[0]).strip()
        alt_name = str(row.iloc[14]).strip()

        if not alt_name or alt_name == "nan" or alt_name == "":
            fuzzy_results.append("No Fuzzy Match")
            no_match_count += 1
            checked += 1
            continue

        is_match = fuzzy_match(search_name, alt_name)
        checked += 1

        if is_match:
            fuzzy_results.append("Yes Fuzzy Match")
            match_count += 1
            print(f"  YES: '{search_name}' ~ '{alt_name}'")
        else:
            fuzzy_results.append("No Fuzzy Match")
            no_match_count += 1
            print(f"  NO:  '{search_name}' X '{alt_name}'")

    df["Fuzzy Match"] = fuzzy_results

    # Save
    df.to_excel(input_file, index=False, engine="openpyxl")

    print(f"\nDone! Updated {input_file}")
    print(f"  Checked: {checked} rows")
    print(f"  Yes Fuzzy Match: {match_count}")
    print(f"  No Fuzzy Match: {no_match_count}")


if __name__ == "__main__":
    main()
