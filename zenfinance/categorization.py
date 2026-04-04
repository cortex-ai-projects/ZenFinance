"""
ZenFinance — Rule-based Categorization Engine
Applies regex patterns to bank_description / details to assign categories.
"""
from __future__ import annotations

import re
from typing import Optional

import pandas as pd

# ──────────────────────────────────────────────────────────
# Category Rules
# Each entry: (category, sub_category, [regex_patterns])
# Patterns are tested (case-insensitive) against bank_description + details
# ──────────────────────────────────────────────────────────
CATEGORY_RULES: list[tuple[str, str, list[str]]] = [
    # Food & Dining
    ("Food & Dining", "Restaurants",   [r"swiggy", r"zomato", r"dominos?", r"pizza", r"burger", r"kfc", r"mcdonalds?", r"subway", r"barbeque\s*nation", r"haldirams?"]),
    ("Food & Dining", "Groceries",     [r"bigbasket", r"grofers", r"blinkit", r"zepto", r"dmart", r"more\s*supermarket", r"reliance\s*(fresh|smart)", r"grocery"]),
    ("Food & Dining", "Cafes",         [r"starbucks", r"ccd", r"cafe\s*coffee\s*day", r"chai\s*point", r"barista", r"third\s*wave"]),

    # Transportation
    ("Transportation", "Ride-Hailing", [r"uber", r"ola\s*(cabs?)?", r"rapido", r"namma\s*yatri", r"indrive"]),
    ("Transportation", "Fuel",         [r"hp\s*petrol", r"indian\s*oil", r"bharat\s*petroleum", r"iocl", r"essar\s*oil", r"petrol", r"fuel"]),
    ("Transportation", "Metro/Bus",    [r"dmrc", r"bmtc", r"ksrtc", r"metro\s*(card)?", r"transit"]),
    ("Transportation", "Train/Flights",[r"irctc", r"indian\s*railways?", r"air\s*india", r"indigo", r"vistara", r"spicejet", r"goair", r"makemytrip", r"yatra", r"cleartrip"]),

    # Shopping
    ("Shopping", "E-Commerce",         [r"amazon", r"flipkart", r"myntra", r"ajio", r"nykaa", r"meesho", r"snapdeal"]),
    ("Shopping", "Electronics",        [r"croma", r"reliance\s*digital", r"vijay\s*sales", r"apple\s*(store)?", r"samsung\s*(store)?"]),
    ("Shopping", "Clothing",           [r"h&m", r"zara", r"uniqlo", r"westside", r"pantaloons", r"lifestyle", r"max\s*fashion"]),

    # Utilities & Bills
    ("Utilities", "Electricity",       [r"bescom", r"mseb", r"tata\s*power", r"adani\s*(electricity|power)", r"electricity\s*bill"]),
    ("Utilities", "Water",             [r"bwssb", r"water\s*supply", r"jal\s*board"]),
    ("Utilities", "Gas",               [r"mahanagar\s*gas", r"indraprastha\s*gas", r"igl\s*", r"gas\s*bill"]),
    ("Utilities", "Internet",          [r"airtel\s*(broadband|fiber)?", r"jio\s*(fiber)?", r"act\s*fibernet", r"bsnl", r"broadband"]),
    ("Utilities", "Mobile",            [r"airtel\s*(mobile|prepaid)?", r"jio\s*(mobile)?", r"vodafone", r"vi\s*(mobile)?", r"bsnl\s*(mobile)?"]),

    # Entertainment
    ("Entertainment", "OTT",           [r"netflix", r"amazon\s*prime", r"hotstar", r"disney\+?", r"zee5", r"sonyliv", r"jiocinema", r"youtube\s*premium", r"spotify", r"gaana"]),
    ("Entertainment", "Gaming",        [r"steam", r"playstation", r"xbox", r"google\s*play\s*games", r"apple\s*arcade"]),
    ("Entertainment", "Movies",        [r"bookmyshow", r"pvr", r"inox", r"cinepolis"]),

    # Health & Wellness
    ("Health", "Pharmacy",             [r"1mg", r"netmeds", r"apollo\s*pharmacy", r"medplus", r"pharmeasy", r"pharmacy"]),
    ("Health", "Hospital/Clinic",      [r"apollo\s*hospital", r"fortis", r"max\s*hospital", r"aiims", r"clinic", r"hospital", r"nursing\s*home"]),
    ("Health", "Fitness",              [r"cult\.fit", r"anytime\s*fitness", r"gold\s*gym", r"gym\s*fee"]),

    # Finance
    ("Finance", "Insurance",           [r"lic\b", r"hdfc\s*life", r"icici\s*(prudential|lombard)", r"star\s*health", r"bajaj\s*(allianz|finserv)", r"insurance"]),
    ("Finance", "Mutual Funds",        [r"zerodha\s*coin", r"groww", r"paytm\s*money", r"kuvera", r"mutual\s*fund", r"sip\s*"]),
    ("Finance", "EMI",                 [r"emi\b", r"loan\s*(repay|payment)?", r"emi\s*debit"]),
    ("Finance", "Credit Card",         [r"credit\s*card\s*(bill|payment|due)", r"cc\s*bill"]),
    ("Finance", "Savings/Transfer",    [r"neft", r"imps", r"rtgs", r"fund\s*transfer", r"self\s*transfer"]),

    # Housing
    ("Housing", "Rent",                [r"house\s*rent", r"rent\s*payment", r"rental", r"pg\s*rent", r"accommodation"]),
    ("Housing", "Maintenance",         [r"society\s*(maintenance|fee)", r"maintenance\s*(charges?)?", r"housing\s*society"]),

    # Income
    ("Income", "Salary",               [r"salary", r"sal\s*credit", r"wages", r"payroll", r"tata\s*(motors|consul|tcs|elxsi)", r"infosys", r"wipro", r"accenture"]),
    ("Income", "Freelance",            [r"freelance", r"upwork", r"fiverr", r"payoneer"]),
    ("Income", "Interest",             [r"credit\s*interest", r"int\s*credit", r"interest\s*credit", r"fd\s*interest"]),
    ("Income", "Refund",               [r"refund", r"cashback", r"reversal", r"chargeback"]),

    # Delivery & Quick Commerce
    ("Delivery", "Quick Commerce",     [r"zepto", r"blinkit", r"swiggy\s*instamart", r"dunzo", r"bigbasket\s*bb\s*now"]),
    ("Delivery", "E-Commerce",         [r"amazon\s*(seller|logistics)", r"flipkart\s*delivery", r"delhivery", r"shiprocket", r"ecom\s*express"]),

    # Education
    ("Education", "Tuition/Courses",   [r"udemy", r"coursera", r"unacademy", r"byju", r"vedantu", r"upgrad", r"simplilearn"]),
    ("Education", "Books",             [r"amazon\s*books", r"flipkart\s*books", r"crossword", r"landmark"]),

    # Travel
    ("Travel", "Hotels",               [r"oyo", r"treebo", r"fabhotel", r"taj\s*hotel", r"marriott", r"hilton", r"airbnb", r"hotel"]),
    ("Travel", "Cab/Taxi",             [r"uber\s*(travel|outstatio)", r"ola\s*(outstatio|travel)", r"savaari"]),
]


def categorize(bank_description: str, details: Optional[str] = None) -> tuple[str, str]:
    """
    Apply regex rules to description + details.
    Returns (category, sub_category). Falls back to ('Uncategorized', 'General').
    """
    text = " ".join(filter(None, [bank_description, details])).lower()
    for category, sub_category, patterns in CATEGORY_RULES:
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return category, sub_category
    return "Uncategorized", "General"


def apply_categories(df: pd.DataFrame) -> pd.DataFrame:
    """
    Bulk-apply categorization to a DataFrame.
    Only fills rows where category is null/Uncategorized.
    """
    needs_cat = df["category"].isna() | (df["category"] == "Uncategorized") | (df["category"] == "")
    if needs_cat.any():
        results = df[needs_cat].apply(
            lambda r: pd.Series(
                categorize(str(r.get("bank_description", "")), str(r.get("details", ""))),
                index=["category", "sub_category"],
            ),
            axis=1,
        )
        df.loc[needs_cat, "category"]     = results["category"].values
        df.loc[needs_cat, "sub_category"] = results["sub_category"].values
    return df


def get_all_categories() -> list[str]:
    seen = []
    for cat, _, _ in CATEGORY_RULES:
        if cat not in seen:
            seen.append(cat)
    seen.append("Uncategorized")
    return seen
