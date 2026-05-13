"""Predefined agent (staff) auto-guidelines per detected intent — pairs with LLM copilot."""

from __future__ import annotations

from typing import Any

# Task keys align with enrich_turn intent enum
AGENT_GUIDELINES: dict[str, dict[str, Any]] = {
    "account_opening": {
        "task_label": "Account opening",
        "priority": "high",
        "auto_checklist": [
            "Confirm purpose of account (savings / current / minor / joint).",
            "Validate OVD set per RBI KYC; capture CKYC number if quoted.",
            "Explain minimum balance & schedule of charges before signature.",
            "Capture nominee: name, relationship, DOB if minor.",
            "Do not open account without completed KYC / in-person verification per policy.",
        ],
        "dos": [
            "Offer accessible formats for key terms if customer asks.",
            "Read back mobile number and email once for accuracy.",
        ],
        "donts": [
            "Do not promise interest rates beyond published board / system.",
            "Do not skip nominee discussion for retail savings.",
        ],
        "escalate_when": ["PEP match", "Sanctions list hit", "Structuring suspicion", "Refuses valid KYC"],
    },
    "loan_enquiry": {
        "task_label": "Loan enquiry",
        "priority": "high",
        "auto_checklist": [
            "Clarify product: home / personal / gold / vehicle / business.",
            "Collect income proof type; explain underwriting is separate from enquiry.",
            "Share only illustrative EMI; state final terms subject to approval.",
            "Obtain consent for bureau pull if moving to application.",
        ],
        "dos": [
            "Document stated income band without committing approval.",
            "Refer to credit policy for max LTV / tenure caps.",
        ],
        "donts": [
            "No guaranteed sanction or same-day disbursal promises.",
            "Do not discourage statutory cooling-off disclosures where applicable.",
        ],
        "escalate_when": ["Fraud indicators", "Third-party applying without mandate", "Coercion suspected"],
    },
    "card_dispute": {
        "task_label": "Card dispute / fraud",
        "priority": "high",
        "auto_checklist": [
            "Establish card possession; last successful txn if safe to ask.",
            "Hotlist if customer confirms unauthorised use.",
            "Explain dispute TAT and provisional credit rules at high level.",
            "Log dispute reference in CRM.",
        ],
        "dos": [
            "Advise customer to monitor SMS / app alerts.",
            "Suggest police FIR if large unauthorised spend and customer willing.",
        ],
        "donts": [
            "Do not confirm chargeback outcome upfront.",
            "Never ask for full CVV or net banking password.",
        ],
        "escalate_when": ["Mule account suspicion", "Insider collusion hint", "Repeated disputes pattern"],
    },
    "remittance": {
        "task_label": "Remittance / FX",
        "priority": "medium",
        "auto_checklist": [
            "Verify purpose code / LRS limits if outward remittance.",
            "Match beneficiary name with KYC; flag SWIFT field errors early.",
            "Confirm charges: cable, correspondent, FX spread disclosure.",
        ],
        "dos": ["Use CBS rate snapshot timestamp in notes.", "Offer printed quote where policy allows."],
        "donts": ["No structuring to avoid LRS caps.", "No unverified crypto off-ramp discussion."],
        "escalate_when": ["Sanctions geography", "High-risk corridor", "Mismatch in purpose vs profile"],
    },
    "locker": {
        "task_label": "Locker visit / allotment",
        "priority": "medium",
        "auto_checklist": [
            "Check agreement, rent, key status.",
            "Witness opening only per dual-control SOP.",
            "Log visit in locker module.",
        ],
        "dos": ["Confirm identity before handover.", "Remind nomination / joint operation rules."],
        "donts": ["Do not custody customer valuables outside locker.", "No side arrangements on waitlist."],
        "escalate_when": ["Court order", "Death of hirer", "Sealed locker hold"],
    },
    "generic": {
        "task_label": "General service",
        "priority": "low",
        "auto_checklist": [
            "Greet and confirm preferred language.",
            "Authenticate before balance or PII.",
            "Summarise next steps and timelines.",
        ],
        "dos": ["Stay within published product facts.", "Offer printed FAQ where available."],
        "donts": ["No legal/tax advice; refer to professionals.", "No sharing another customer's data."],
        "escalate_when": ["Threats", "Media / legal mention", "Regulator escalation request"],
    },
}


def guidelines_for_intent(intent: str | None) -> dict[str, Any]:
    key = intent if intent in AGENT_GUIDELINES else "generic"
    g = AGENT_GUIDELINES[key]
    return {
        "task_key": key,
        "task_label": g["task_label"],
        "priority": g["priority"],
        "auto_checklist": g["auto_checklist"],
        "dos": g["dos"],
        "donts": g["donts"],
        "escalate_when": g["escalate_when"],
    }
