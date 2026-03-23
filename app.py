import os
import time

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("COMPANIES_HOUSE_API_KEY", "")
BASE_URL = "https://api.company-information.service.gov.uk"


def search_companies(query):
    """Search for companies by name."""
    resp = requests.get(
        f"{BASE_URL}/search/companies",
        params={"q": query, "items_per_page": 20},
        auth=(API_KEY, ""),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_company_profile(company_number):
    """Fetch full company profile."""
    resp = requests.get(
        f"{BASE_URL}/company/{company_number}",
        auth=(API_KEY, ""),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def format_address(addr):
    """Format an address dict into a readable string."""
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
    """Check if company address matches the given postcode."""
    if not postcode:
        return True
    addr = company_data.get("address", {}) or company_data.get("registered_office_address", {})
    company_postcode = (addr.get("postal_code", "") or "").replace(" ", "").upper()
    search_postcode = postcode.replace(" ", "").upper()
    return search_postcode in company_postcode or company_postcode in search_postcode


def is_northern_ireland(addr):
    """Check if an address is in Northern Ireland."""
    if not addr:
        return False
    country = (addr.get("country", "") or "").upper()
    region = (addr.get("region", "") or "").upper()
    postcode = (addr.get("postal_code", "") or "").replace(" ", "").upper()
    return (
        "NORTHERN IRELAND" in country
        or "NORTHERN IRELAND" in region
        or postcode.startswith("BT")
    )


def display_company_profile(profile):
    """Display all available company information."""
    st.subheader(profile.get("company_name", "Unknown"))

    # Northern Ireland flag
    reg_addr = profile.get("registered_office_address", {})
    if is_northern_ireland(reg_addr):
        st.error("Northern Ireland Address")

    # Status
    status = profile.get("company_status", "Unknown")
    status_detail = profile.get("company_status_detail", "")
    if status.lower() == "active":
        st.success(f"Status: {status.upper()}")
    elif status.lower() == "dissolved":
        st.error(f"Status: {status.upper()}")
    else:
        st.warning(f"Status: {status.upper()}")
    if status_detail:
        st.caption(f"Status detail: {status_detail}")

    # Core info
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Company Number:** " + profile.get("company_number", "N/A"))
        st.markdown("**Company Type:** " + profile.get("type", "N/A"))
        st.markdown("**Jurisdiction:** " + profile.get("jurisdiction", "N/A"))
        st.markdown("**Date of Creation:** " + profile.get("date_of_creation", "N/A"))
        cessation = profile.get("date_of_cessation")
        if cessation:
            st.markdown("**Date of Cessation:** " + cessation)
    with col2:
        st.markdown("**Registered Office Address:**")
        st.text(format_address(profile.get("registered_office_address", {})))
        if profile.get("registered_office_is_in_dispute"):
            st.warning("Registered office is in dispute")
        if profile.get("undeliverable_registered_office_address"):
            st.warning("Registered office address is undeliverable")

    # SIC Codes
    sic_codes = profile.get("sic_codes", [])
    if sic_codes:
        st.markdown("---")
        st.markdown("### SIC Codes")
        for code in sic_codes:
            st.markdown(f"- **{code}** — {SIC_DESCRIPTIONS.get(code, 'Description not available locally')}")
    else:
        st.info("No SIC codes listed for this company.")

    # Accounts
    accounts = profile.get("accounts", {})
    if accounts:
        st.markdown("---")
        st.markdown("### Accounts")
        ref_date = accounts.get("accounting_reference_date", {})
        if ref_date:
            st.markdown(f"**Accounting Reference Date:** {ref_date.get('day', '??')}/{ref_date.get('month', '??')}")
        last_acc = accounts.get("last_accounts", {})
        if last_acc:
            st.markdown(f"**Last Accounts Made Up To:** {last_acc.get('made_up_to', 'N/A')}")
            st.markdown(f"**Last Accounts Type:** {last_acc.get('type', 'N/A')}")
        next_acc = accounts.get("next_accounts", {})
        if next_acc:
            st.markdown(f"**Next Accounts Due:** {next_acc.get('due_on', 'N/A')}")
            st.markdown(f"**Next Accounts Period Start:** {next_acc.get('period_start_on', 'N/A')}")
            st.markdown(f"**Next Accounts Period End:** {next_acc.get('period_end_on', 'N/A')}")
        if accounts.get("overdue"):
            st.error("Accounts are OVERDUE")

    # Confirmation Statement
    conf = profile.get("confirmation_statement", {})
    if conf:
        st.markdown("---")
        st.markdown("### Confirmation Statement")
        st.markdown(f"**Last Made Up To:** {conf.get('last_made_up_to', 'N/A')}")
        st.markdown(f"**Next Due:** {conf.get('next_due', 'N/A')}")
        if conf.get("overdue"):
            st.error("Confirmation statement is OVERDUE")

    # Additional fields
    st.markdown("---")
    st.markdown("### Additional Information")
    extra_fields = {
        "has_been_liquidated": "Has Been Liquidated",
        "has_insolvency_history": "Has Insolvency History",
        "has_charges": "Has Charges",
        "has_super_secure_pscs": "Has Super Secure PSCs",
        "can_file": "Can File",
        "etag": "ETag",
        "external_registration_number": "External Registration Number",
        "foreign_company_details": "Foreign Company Details",
        "is_community_interest_company": "Is Community Interest Company",
        "subtype": "Subtype",
        "last_full_members_list_date": "Last Full Members List Date",
    }
    displayed_extra = False
    for key, label in extra_fields.items():
        value = profile.get(key)
        if value is not None:
            displayed_extra = True
            st.markdown(f"**{label}:** {value}")
    if not displayed_extra:
        st.caption("No additional information available.")

    # Previous company names
    prev_names = profile.get("previous_company_names", [])
    if prev_names:
        st.markdown("---")
        st.markdown("### Previous Company Names")
        for entry in prev_names:
            name = entry.get("name", "N/A")
            eff_from = entry.get("effective_from", "N/A")
            ceased = entry.get("ceased_on", "N/A")
            st.markdown(f"- **{name}** (from {eff_from} to {ceased})")

    # Raw JSON expander
    with st.expander("View raw API response"):
        st.json(profile)


# Common SIC code descriptions (top ~200 codes)
SIC_DESCRIPTIONS = {
    "01110": "Growing of cereals (except rice), leguminous crops and oil seeds",
    "01120": "Growing of rice",
    "01130": "Growing of vegetables and melons, roots and tubers",
    "01140": "Growing of sugar cane",
    "01150": "Growing of tobacco",
    "01160": "Growing of fibre crops",
    "01190": "Growing of other non-perennial crops",
    "01210": "Growing of grapes",
    "01220": "Growing of tropical and subtropical fruits",
    "01230": "Growing of citrus fruits",
    "01240": "Growing of pome fruits and stone fruits",
    "01250": "Growing of other tree and bush fruits and nuts",
    "01260": "Growing of oleaginous fruits",
    "01270": "Growing of beverage crops",
    "01280": "Growing of spices, aromatic, drug and pharmaceutical crops",
    "01290": "Growing of other perennial crops",
    "01300": "Plant propagation",
    "01410": "Raising of dairy cattle",
    "01420": "Raising of other cattle and buffaloes",
    "01430": "Raising of horses and other equines",
    "01440": "Raising of camels and camelids",
    "01450": "Raising of sheep and goats",
    "01460": "Raising of swine/pigs",
    "01470": "Raising of poultry",
    "01490": "Raising of other animals",
    "01500": "Mixed farming",
    "01610": "Support activities for crop production",
    "01620": "Support activities for animal production",
    "01630": "Post-harvest crop activities",
    "01640": "Seed processing for propagation",
    "01700": "Hunting, trapping and related service activities",
    "02100": "Silviculture and other forestry activities",
    "02200": "Logging",
    "02300": "Gathering of wild growing non-wood products",
    "02400": "Support services to forestry",
    "03110": "Marine fishing",
    "03120": "Freshwater fishing",
    "03210": "Marine aquaculture",
    "03220": "Freshwater aquaculture",
    "10110": "Processing and preserving of meat",
    "10120": "Processing and preserving of poultry meat",
    "10200": "Processing and preserving of fish, crustaceans and molluscs",
    "10310": "Processing and preserving of potatoes",
    "10320": "Manufacture of fruit and vegetable juice",
    "10390": "Other processing and preserving of fruit and vegetables",
    "10410": "Manufacture of oils and fats",
    "10420": "Manufacture of margarine and similar edible fats",
    "10510": "Operation of dairies and cheese making",
    "10520": "Manufacture of ice cream",
    "10610": "Manufacture of grain mill products",
    "10620": "Manufacture of starches and starch products",
    "10710": "Manufacture of bread; manufacture of fresh pastry goods and cakes",
    "10720": "Manufacture of rusks and biscuits; manufacture of preserved pastry goods and cakes",
    "10730": "Manufacture of macaroni, noodles, couscous and similar farinaceous products",
    "10810": "Manufacture of sugar",
    "10820": "Manufacture of cocoa, chocolate and sugar confectionery",
    "10830": "Processing of tea and coffee",
    "10840": "Manufacture of condiments and seasonings",
    "10850": "Manufacture of prepared meals and dishes",
    "10860": "Manufacture of homogenised food preparations and dietetic food",
    "10890": "Manufacture of other food products n.e.c.",
    "10910": "Manufacture of prepared feeds for farm animals",
    "10920": "Manufacture of prepared pet foods",
    "11010": "Distilling, rectifying and blending of spirits",
    "11020": "Manufacture of wine from grape",
    "11030": "Manufacture of cider and other fruit wines",
    "11040": "Manufacture of other non-distilled fermented beverages",
    "11050": "Manufacture of beer",
    "11060": "Manufacture of malt",
    "11070": "Manufacture of soft drinks; production of mineral waters and other bottled waters",
    "41100": "Development of building projects",
    "41201": "Construction of commercial buildings",
    "41202": "Construction of domestic buildings",
    "42110": "Construction of roads and motorways",
    "42120": "Construction of railways and underground railways",
    "42130": "Construction of bridges and tunnels",
    "42210": "Construction of utility projects for fluids",
    "42220": "Construction of utility projects for electricity and telecommunications",
    "42910": "Construction of water projects",
    "42990": "Construction of other civil engineering projects n.e.c.",
    "43110": "Demolition",
    "43120": "Site preparation",
    "43130": "Test drilling and boring",
    "43210": "Electrical installation",
    "43220": "Plumbing, heat and air-conditioning installation",
    "43290": "Other construction installation",
    "43310": "Plastering",
    "43320": "Joinery installation",
    "43330": "Floor and wall covering",
    "43341": "Painting",
    "43342": "Glazing",
    "43390": "Other building completion and finishing",
    "43910": "Roofing activities",
    "43990": "Other specialised construction activities n.e.c.",
    "45111": "Sale of new cars and light motor vehicles",
    "45112": "Sale of used cars and light motor vehicles",
    "45190": "Sale of other motor vehicles",
    "45200": "Maintenance and repair of motor vehicles",
    "45310": "Wholesale trade of motor vehicle parts and accessories",
    "45320": "Retail trade of motor vehicle parts and accessories",
    "45400": "Sale, maintenance and repair of motorcycles and related parts and accessories",
    "46110": "Agents involved in the sale of agricultural raw materials, live animals, textile raw materials and semi-finished goods",
    "46120": "Agents involved in the sale of fuels, ores, metals and industrial chemicals",
    "46130": "Agents involved in the sale of timber and building materials",
    "46140": "Agents involved in the sale of machinery, industrial equipment, ships and aircraft",
    "46150": "Agents involved in the sale of furniture, household goods, hardware and ironmongery",
    "46160": "Agents involved in the sale of textiles, clothing, fur, footwear and leather goods",
    "46170": "Agents involved in the sale of food, beverages and tobacco",
    "46180": "Agents specialised in the sale of other particular products",
    "46190": "Agents involved in the sale of a variety of goods",
    "47110": "Retail sale in non-specialised stores with food, beverages or tobacco predominating",
    "47190": "Other retail sale in non-specialised stores",
    "47210": "Retail sale of fruit and vegetables in specialised stores",
    "47220": "Retail sale of meat and meat products in specialised stores",
    "47230": "Retail sale of fish, crustaceans and molluscs in specialised stores",
    "47240": "Retail sale of bread, cakes, flour confectionery and sugar confectionery in specialised stores",
    "47250": "Retail sale of beverages in specialised stores",
    "47260": "Retail sale of tobacco products in specialised stores",
    "47290": "Other retail sale of food in specialised stores",
    "47300": "Retail sale of automotive fuel in specialised stores",
    "47410": "Retail sale of computers, peripheral units and software in specialised stores",
    "47420": "Retail sale of telecommunications equipment in specialised stores",
    "47430": "Retail sale of audio and video equipment in specialised stores",
    "47510": "Retail sale of textiles in specialised stores",
    "47520": "Retail sale of hardware, paints and glass in specialised stores",
    "47530": "Retail sale of carpets, rugs, wall and floor coverings in specialised stores",
    "47540": "Retail sale of electrical household appliances in specialised stores",
    "47590": "Retail sale of furniture, lighting equipment and other household articles in specialised stores",
    "47610": "Retail sale of books in specialised stores",
    "47620": "Retail sale of newspapers and stationery in specialised stores",
    "47630": "Retail sale of music and video recordings in specialised stores",
    "47640": "Retail sale of sports goods, fishing gear, camping goods, boats and bicycles",
    "47650": "Retail sale of games and toys in specialised stores",
    "47710": "Retail sale of clothing in specialised stores",
    "47720": "Retail sale of footwear and leather goods in specialised stores",
    "47730": "Dispensing chemist in specialised stores",
    "47740": "Retail sale of medical and orthopaedic goods in specialised stores",
    "47750": "Retail sale of cosmetic and toilet articles in specialised stores",
    "47760": "Retail sale of flowers, plants, seeds, fertilisers, pet animals and pet food in specialised stores",
    "47770": "Retail sale of watches and jewellery in specialised stores",
    "47780": "Other retail sale of new goods in specialised stores",
    "47790": "Retail sale of second-hand goods in stores",
    "47810": "Retail sale via stalls and markets of food, beverages and tobacco products",
    "47820": "Retail sale via stalls and markets of textiles, clothing and footwear",
    "47890": "Retail sale via stalls and markets of other goods",
    "47910": "Retail sale via mail order houses or via Internet",
    "47990": "Other retail sale not in stores, stalls or markets",
    "56101": "Licensed restaurants",
    "56102": "Unlicensed restaurants and cafes",
    "56103": "Take-away food shops and mobile food stands",
    "56210": "Event catering activities",
    "56301": "Licensed clubs",
    "56302": "Public houses and bars",
    "62011": "Ready-made interactive leisure and entertainment software development",
    "62012": "Business and domestic software development",
    "62020": "Information technology consultancy activities",
    "62030": "Computer facilities management activities",
    "62090": "Other information technology service activities",
    "63110": "Data processing, hosting and related activities",
    "63120": "Web portals",
    "63910": "News agency activities",
    "63990": "Other information service activities n.e.c.",
    "64110": "Central banking",
    "64191": "Banks",
    "64192": "Building societies",
    "64201": "Activities of financial services holding companies",
    "64202": "Activities of non-financial services holding companies",
    "64205": "Activities of head offices",
    "64209": "Activities of other holding companies n.e.c.",
    "64301": "Activities of investment trusts",
    "64302": "Activities of unit trusts",
    "64303": "Activities of venture and development capital companies",
    "64304": "Activities of open-ended investment companies",
    "64305": "Activities of property unit trusts",
    "64306": "Activities of real estate investment trusts",
    "64910": "Financial leasing",
    "64921": "Credit granting by non-deposit taking finance houses and other specialist consumer credit grantors",
    "64922": "Activities of mortgage finance companies",
    "64929": "Other credit granting n.e.c.",
    "64991": "Security dealing on own account",
    "64992": "Factoring",
    "64999": "Financial intermediation not elsewhere classified",
    "66110": "Administration of financial markets",
    "66120": "Security and commodity contracts dealing activities",
    "66190": "Other activities auxiliary to financial intermediation",
    "66210": "Risk and damage evaluation",
    "66220": "Activities of insurance agents and brokers",
    "66290": "Other activities auxiliary to insurance and pension funding",
    "66300": "Fund management activities",
    "68100": "Buying and selling of own real estate",
    "68201": "Renting and operating of Housing Association real estate",
    "68202": "Letting and operating of conference and exhibition centres",
    "68209": "Other letting and operating of own or leased real estate",
    "68310": "Real estate agencies",
    "68320": "Management of real estate on a fee or contract basis",
    "69101": "Barristers at law",
    "69102": "Solicitors",
    "69109": "Activities of patent and copyright agents; other legal activities n.e.c.",
    "69201": "Accounting and auditing activities",
    "69202": "Bookkeeping activities",
    "69203": "Tax consultancy",
    "70100": "Activities of head offices",
    "70210": "Public relations and communications activities",
    "70221": "Financial management",
    "70229": "Management consultancy activities (other than financial management)",
    "71111": "Architectural activities",
    "71112": "Urban planning and landscape architectural activities",
    "71121": "Engineering design activities for industrial process and production",
    "71122": "Engineering related scientific and technical consulting activities",
    "71129": "Other engineering activities",
    "71200": "Technical testing and analysis",
    "72110": "Research and experimental development on biotechnology",
    "72190": "Other research and experimental development on natural sciences and engineering",
    "72200": "Research and experimental development on social sciences and humanities",
    "73110": "Advertising agencies",
    "73120": "Media representation services",
    "73200": "Market research and public opinion polling",
    "74100": "Specialised design activities",
    "74201": "Portrait photographic activities",
    "74202": "Other specialist photography",
    "74209": "Photographic activities not elsewhere classified",
    "74300": "Translation and interpretation activities",
    "74901": "Environmental consulting activities",
    "74902": "Quantity surveying activities",
    "74909": "Other professional, scientific and technical activities n.e.c.",
    "74990": "Non-trading company",
    "77110": "Renting and leasing of cars and light motor vehicles",
    "77210": "Renting and leasing of recreational and sports goods",
    "77310": "Renting and leasing of agricultural machinery and equipment",
    "77320": "Renting and leasing of construction and civil engineering machinery and equipment",
    "77330": "Renting and leasing of office machinery and equipment (including computers)",
    "77340": "Renting and leasing of water transport equipment",
    "77350": "Renting and leasing of air transport equipment",
    "77390": "Renting and leasing of other machinery, equipment and tangible goods n.e.c.",
    "77400": "Leasing of intellectual property and similar products, except copyrighted works",
    "78100": "Activities of employment placement agencies",
    "78200": "Temporary employment agency activities",
    "78300": "Human resources provision and management of human resources functions",
    "79110": "Travel agency activities",
    "79120": "Tour operator activities",
    "79900": "Other reservation service and related activities",
    "80100": "Private security activities",
    "80200": "Security systems service activities",
    "80300": "Investigation activities",
    "81100": "Combined facilities support activities",
    "81210": "General cleaning of buildings",
    "81221": "Window cleaning services",
    "81222": "Specialised cleaning services",
    "81223": "Furnace and chimney cleaning services",
    "81229": "Other building and industrial cleaning activities",
    "81300": "Landscape service activities",
    "82110": "Combined office administrative service activities",
    "82190": "Photocopying, document preparation and other specialised office support activities",
    "82200": "Activities of call centres",
    "82301": "Activities of exhibition and fair organisers",
    "82302": "Activities of conference organisers",
    "82910": "Activities of collection agencies and credit bureaus",
    "82920": "Packaging activities",
    "82990": "Other business support service activities n.e.c.",
    "84110": "General public administration activities",
    "85100": "Pre-primary education",
    "85200": "Primary education",
    "85310": "General secondary education",
    "85320": "Technical and vocational secondary education",
    "85410": "Post-secondary non-tertiary education",
    "85421": "First-degree level higher education",
    "85422": "Post-graduate level higher education",
    "85510": "Sports and recreation education",
    "85520": "Cultural education",
    "85530": "Driving school activities",
    "85590": "Other education n.e.c.",
    "85600": "Educational support activities",
    "86101": "Hospital activities",
    "86102": "Medical nursing home activities",
    "86210": "General medical practice activities",
    "86220": "Specialist medical practice activities",
    "86230": "Dental practice activities",
    "86900": "Other human health activities",
    "87100": "Residential nursing care activities",
    "87200": "Residential care activities for learning difficulties, mental health and substance abuse",
    "87300": "Residential care activities for the elderly and disabled",
    "87900": "Other residential care activities",
    "88100": "Social work activities without accommodation for the elderly and disabled",
    "88910": "Child day-care activities",
    "88990": "Other social work activities without accommodation n.e.c.",
    "90010": "Performing arts",
    "90020": "Support activities to performing arts",
    "90030": "Artistic creation",
    "90040": "Operation of arts facilities",
    "91011": "Library activities",
    "91012": "Archive activities",
    "91020": "Museum activities",
    "91030": "Operation of historical sites and buildings and similar visitor attractions",
    "91040": "Botanical and zoological gardens and nature reserve activities",
    "93110": "Operation of sports facilities",
    "93120": "Activities of sport clubs",
    "93130": "Fitness facilities",
    "93190": "Other sports activities",
    "93210": "Activities of amusement parks and theme parks",
    "93290": "Other amusement and recreation activities",
    "94110": "Activities of business and employers membership organisations",
    "94120": "Activities of professional membership organisations",
    "94200": "Activities of trade unions",
    "94910": "Activities of religious organisations",
    "94920": "Activities of political organisations",
    "94990": "Activities of other membership organisations n.e.c.",
    "95110": "Repair of computers and peripheral equipment",
    "95120": "Repair of communication equipment",
    "95210": "Repair of consumer electronics",
    "95220": "Repair of household appliances and home and garden equipment",
    "95230": "Repair of footwear and leather goods",
    "95240": "Repair of furniture and home furnishings",
    "95250": "Repair of watches, clocks and jewellery",
    "95290": "Repair of other personal and household goods",
    "96010": "Washing and (dry-)cleaning of textile and fur products",
    "96020": "Hairdressing and other beauty treatment",
    "96030": "Funeral and related activities",
    "96040": "Physical well-being activities",
    "96090": "Other service activities n.e.c.",
    "97000": "Activities of households as employers of domestic personnel",
    "98000": "Undifferentiated goods-and services-producing activities of private households for own use",
    "98100": "Undifferentiated goods-producing activities of private households for own use",
    "98200": "Undifferentiated service-producing activities of private households for own use",
    "99000": "Activities of extraterritorial organisations and bodies",
    "99999": "Dormant company",
}

# --- Streamlit App ---

st.set_page_config(page_title="Companies House Lookup", page_icon="🏢", layout="wide")
st.title("Companies House Lookup")
st.caption("Search UK companies and view SIC codes, status, and full profile data.")

if not API_KEY or API_KEY == "your_api_key_here":
    st.error(
        "Please set your Companies House API key in the `.env` file. "
        "Get a free key at https://developer.company-information.service.gov.uk"
    )
    st.stop()

search_tab, upload_tab = st.tabs(["Single Search", "Excel Batch Search"])

with search_tab:
    col_name, col_postcode = st.columns([3, 1])
    with col_name:
        company_name = st.text_input("Company Name", placeholder="e.g. Tesco")
    with col_postcode:
        postcode = st.text_input("Postcode (optional filter)", placeholder="e.g. AL1 1AB")

    if st.button("Search", type="primary", key="single_search") and company_name:
        with st.spinner("Searching Companies House..."):
            try:
                results = search_companies(company_name)
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 401:
                    st.error("Invalid API key. Please check your `.env` file.")
                else:
                    st.error(f"API error: {e.response.status_code} — {e.response.text}")
                st.stop()
            except requests.exceptions.RequestException as e:
                st.error(f"Request failed: {e}")
                st.stop()

        items = results.get("items", [])
        if not items:
            st.warning("No companies found for that search.")
            st.stop()

        # Filter by postcode if provided
        if postcode:
            filtered = [item for item in items if matches_postcode(item, postcode)]
            if not filtered:
                st.warning(f"Found {len(items)} companies but none match postcode '{postcode}'. Showing all results.")
                filtered = items
            else:
                st.info(f"Showing {len(filtered)} of {len(items)} results matching postcode '{postcode}'.")
            items = filtered

        st.markdown(f"### Found {len(items)} company/companies")

        for item in items:
            company_number = item.get("company_number", "")
            title = item.get("title", "Unknown")
            status = item.get("company_status", "unknown")
            ni_tag = " \U0001f534 NI" if is_northern_ireland(item.get("address", {})) else ""

            with st.expander(f"{title} — {company_number} ({status.upper()}){ni_tag}"):
                with st.spinner("Loading full profile..."):
                    try:
                        profile = get_company_profile(company_number)
                        display_company_profile(profile)
                    except requests.exceptions.RequestException as e:
                        st.error(f"Could not load profile for {company_number}: {e}")

with upload_tab:
    uploaded_file = st.file_uploader("Upload an Excel file with company names", type=["xlsx", "xls"])

    if uploaded_file is not None:
        try:
            df = pd.read_excel(uploaded_file)
        except Exception as e:
            st.error(f"Could not read Excel file: {e}")
            st.stop()

        if df.empty:
            st.warning("The uploaded file is empty.")
            st.stop()

        column = st.selectbox("Select the column containing company names", options=df.columns.tolist())

        if st.button("Search All Companies", type="primary", key="batch_search"):
            names = df[column].dropna().astype(str).unique().tolist()
            if not names:
                st.warning("No company names found in the selected column.")
                st.stop()

            st.info(f"Searching for {len(names)} companies...")
            progress = st.progress(0)

            for i, name in enumerate(names):
                progress.progress((i + 1) / len(names), text=f"Searching {i + 1}/{len(names)}: {name}")
                try:
                    results = search_companies(name)
                except requests.exceptions.HTTPError as e:
                    if e.response.status_code == 429:
                        st.warning(f"Rate limited. Waiting before retrying '{name}'...")
                        time.sleep(5)
                        try:
                            results = search_companies(name)
                        except Exception:
                            st.error(f"Failed to search for '{name}' after retry.")
                            continue
                    else:
                        st.error(f"API error searching '{name}': {e.response.status_code}")
                        continue
                except requests.exceptions.RequestException as e:
                    st.error(f"Request failed for '{name}': {e}")
                    continue

                items = results.get("items", [])
                if not items:
                    st.warning(f"No results for '{name}'")
                    continue

                # Show only the top result for each name
                top = items[0]
                company_number = top.get("company_number", "")
                title = top.get("title", "Unknown")
                status = top.get("company_status", "unknown")
                ni_tag = " \U0001f534 NI" if is_northern_ireland(top.get("address", {})) else ""

                with st.expander(f"{title} — {company_number} ({status.upper()}){ni_tag}"):
                    with st.spinner("Loading full profile..."):
                        try:
                            profile = get_company_profile(company_number)
                            display_company_profile(profile)
                        except requests.exceptions.RequestException as e:
                            st.error(f"Could not load profile for {company_number}: {e}")

                # Small delay to avoid hitting rate limits
                time.sleep(0.3)

            progress.empty()
            st.success(f"Finished searching {len(names)} companies.")
