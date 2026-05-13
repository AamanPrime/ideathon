"""Regulatory-style snippets keyed by intent (indicative; not legal advice)."""

from __future__ import annotations

DISCLAIMERS: dict[str, dict[str, list[str]]] = {
    "loan_enquiry": {
        "en": [
            "Interest rates, fees, and eligibility are subject to the bank's credit policy and final documentation.",
            "Illustrative EMI is not a sanction letter; formal approval requires complete underwriting.",
        ],
        "hi": [
            "ब्याज दर, शुल्क और पात्रता बैंक की क्रेडिट नीति व अंतिम दस्तावेज़ों पर निर्भर है।",
            "संकेतक EMI स्वीकृति पत्र नहीं है; पूर्ण अंडरराइटिंग के बाद ही औपचारिक मंजूरी।",
        ],
    },
    "account_opening": {
        "en": [
            "Product features and charges are as per the bank's schedule of charges and product terms.",
            "KYC is mandatory; services may be declined if requirements are not met.",
        ],
        "hi": [
            "उत्पाद विशेषताएँ और शुल्क बैंक की शुल्क अनुसूची व उत्पाद शर्तों के अनुसार हैं।",
            "KYC अनिवार्य है; आवश्यकताएँ पूरी न होने पर सेवाएँ अस्वीकृत हो सकती हैं।",
        ],
    },
    "card_dispute": {
        "en": [
            "Chargeback outcomes depend on card network rules and merchant response timelines.",
            "Do not promise reversal until the dispute workflow confirms eligibility.",
        ],
        "hi": [
            "चार्जबैक परिणाम कार्ड नेटवर्क नियमों व मर्चेंट प्रतिक्रिया समय पर निर्भर करते हैं।",
            "विवाद वर्कफ़्लो पात्रता पुष्टि होने तक उलटफेर का वादा न करें।",
        ],
    },
    "remittance": {
        "en": [
            "FX and remittance limits are subject to RBI FEMA guidelines and bank policy.",
            "Beneficiary details must match KYC records; mismatches may delay or block transfers.",
        ],
        "hi": [
            "विदेशी मुद्रा व प्रेषण सीमाएँ RBI FEMA दिशानिर्देशों व बैंक नीति के अधीन हैं।",
            "लाभार्थी विवरण KYC रिकॉर्ड से मेल खाना चाहिए; असंगति से विलंब या रोक संभव।",
        ],
    },
    "locker": {
        "en": [
            "Locker allotment is subject to availability, agreement terms, and applicable rent / deposit.",
        ],
        "hi": [
            "लॉकर आवंट उपलब्धता, करार की शर्तों व लागू किराया / जमा के अधीन है।",
        ],
    },
    "generic": {
        "en": [
            "Information shared is for customer service; verify identity before disclosing account-specific data.",
        ],
        "hi": [
            "साझा जानकारी ग्राहक सेवा हेतु है; खाता-विशिष्ट डेटा से पहले पहचान सत्यापित करें।",
        ],
    },
}


def disclaimers_for_intent(intent: str | None, staff_lang: str, customer_lang: str) -> dict[str, list[str]]:
    key = intent if intent in DISCLAIMERS else "generic"
    block = DISCLAIMERS[key]
    return {
        "staff_lang": block.get(staff_lang) or block.get("en") or [],
        "customer_lang": block.get(customer_lang) or block.get("hi") or block.get("en") or [],
    }
