"""Static banking glossary for Indian branch context (deterministic hints)."""

BANKING_TERMS: dict[str, str] = {
    "KYC": "Know Your Customer — identity & address verification per RBI norms.",
    "CKYC": "Central KYC — centralised KYC registry reference.",
    "NEFT": "National Electronic Funds Transfer — batch retail transfers.",
    "RTGS": "Real Time Gross Settlement — high-value, real-time settlement.",
    "IMPS": "Immediate Payment Service — instant retail transfers 24x7.",
    "UPI": "Unified Payments Interface — instant bank-to-bank via VPAs.",
    "FD": "Fixed Deposit — term deposit with fixed rate & maturity.",
    "RD": "Recurring Deposit — periodic instalments into a term deposit.",
    "OD": "Overdraft — facility to draw beyond available balance up to a limit.",
    "EMI": "Equated Monthly Instalment — loan repayment schedule.",
    "NPA": "Non-Performing Asset — loan account with overdue beyond threshold.",
    "Lien": "Lien — bank's legal hold on funds or securities.",
    "Nominee": "Nominee — person designated to receive proceeds on death.",
    "IFSC": "Indian Financial System Code — identifies bank branch for transfers.",
    "MICR": "Magnetic Ink Character Recognition — cheque processing code.",
    "CBS": "Core Banking Solution — centralised ledger & accounts system.",
    "AML": "Anti-Money Laundering — monitoring & reporting controls.",
    "PAN": "Permanent Account Number — income-tax identifier in India.",
    "Aadhaar": "Aadhaar — UIDAI-issued 12-digit identity (use masked display in-branch).",
    "GSTIN": "GST Identification Number — indirect tax registration.",
    "ECS": "Electronic Clearing Service — mandate-based debit instructions.",
    "NACH": "National Automated Clearing House — bulk recurring debits/credits.",
    "POS": "Point of Sale — card acceptance terminal.",
    "CVV": "Card Verification Value — do not ask customer to read full card number aloud.",
    "OTP": "One Time Password — transient auth code; never ask staff to repeat customer's OTP aloud in open area.",
}


def find_terms_in_text(text: str) -> list[dict[str, str]]:
    if not text:
        return []
    hits: list[dict[str, str]] = []
    upper = text.upper()
    for term, definition in BANKING_TERMS.items():
        if term.upper() in upper or term in text:
            hits.append({"term": term, "definition": definition})
    return hits[:12]
