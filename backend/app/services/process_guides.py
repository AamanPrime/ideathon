"""Lightweight SOP-style guides keyed by detected intent (demo-grade, extensible)."""

PROCESS_GUIDES: dict[str, dict[str, list[str]]] = {
    "account_opening": {
        "en": [
            "Verify identity: acceptable OVDs per RBI KYC Master Direction.",
            "Capture CKYC / KYC identifier if available; else complete fresh KYC.",
            "Explain minimum balance / product variants; obtain explicit product choice.",
            "Collect nominee details; explain nomination rules.",
            "Provide schedule of charges and key fact statement where applicable.",
        ],
        "hi": [
            "पहचान सत्यापित करें: RBI KYC मास्टर डायरेक्शन के अनुसार स्वीकार्य दस्तावेज़।",
            "यदि उपलब्ध हो तो CKYC / KYC संदर्भ लें; अन्यथा नया KYC पूरा करें।",
            "न्यूनतम शेष / उत्पाद विकल्प समझाएँ; स्पष्ट उत्पाद चयन लें।",
            "नामांकन विवरण लें; नियम समझाएँ।",
            "लागू होने पर शुल्क अनुसूची और मुख्य तथ्य पत्र साझा करें।",
        ],
    },
    "loan_enquiry": {
        "en": [
            "Clarify loan purpose, amount, tenure, and income stability (no guarantees).",
            "Explain eligibility is indicative; sanction subject to credit policy & documentation.",
            "Collect consent for bureau pull and KYC refresh if required.",
            "Share illustrative EMI using standard formula; state final terms may differ.",
        ],
        "hi": [
            "ऋण उद्देश्य, राशि, अवधि और आय की स्थिरता स्पष्ट करें (कोई गारंटी नहीं)।",
            "पात्रता संकेतक है; अंतिम मंजूरी क्रेडिट नीति व दस्तावेज़ों पर निर्भर।",
            "आवश्यकता हो तो ब्यूरो खींचने और KYC रिफ्रेश की सहमति लें।",
            "मानक सूत्र से संकेतक EMI बताएँ; अंतिम शर्तें भिन्न हो सकती हैं।",
        ],
    },
    "card_dispute": {
        "en": [
            "Confirm last recognised transactions and card possession status.",
            "Advise hotlisting if fraud suspected; explain dispute TAT.",
            "Do not promise chargeback outcome; follow issuer network rules.",
        ],
        "hi": [
            "अंतिम मान्य लेनदेन और कार्ड कब्जे की स्थिति पुष्टि करें।",
            "धोखाधड़ी संदेह पर हॉटलिस्टिंग सलाह दें; विवाद समय सीमा समझाएँ।",
            "चार्जबैक परिणाम का वादा न करें; नेटवर्क नियमों का पालन करें।",
        ],
    },
    "generic": {
        "en": [
            "Greet; confirm purpose of visit and preferred language.",
            "Verify customer identity before sharing account-specific information.",
            "Document advice given and any hand-offs.",
        ],
        "hi": [
            "अभिवादन; आगमन उद्देश्य और पसंदीदा भाषा पुष्टि करें।",
            "खाता-विशिष्ट जानकारी से पहले ग्राहक की पहचान सत्यापित करें।",
            "दी गई सलाह और किसी भी हैंडऑफ़ का दस्तावेज़ीकरण करें।",
        ],
    },
}


def guide_for_intent(intent: str | None, lang: str) -> list[str]:
    key = intent if intent in PROCESS_GUIDES else "generic"
    g = PROCESS_GUIDES[key]
    return g.get(lang) or g.get("en") or []
