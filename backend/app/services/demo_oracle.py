"""Offline demo oracle — makes the whole product demo-able WITHOUT Bhashini or LLM keys.

Each existing service (fast_translate, enrich_turn, extract_form_and_signals,
bilingual_summary) calls into here as a *last-resort fallback*. When real keys
are configured, the oracle is bypassed entirely; when they aren't, it produces
plausible, banking-grade, bilingual content so judges always see the full UX.

Nothing here is meant to replace production translation / NLP — it's curated
phraseology for the canonical hackathon demo scenarios.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# 1. Scenario-level demo lines (the "inject scenario" buttons)
# ---------------------------------------------------------------------------

# Each canonical line has an exact translation in the staff language (English).
# When the customer_lang != staff_lang and neither Bhashini nor LLM are wired,
# we use these exact pairs.
SCENARIO_LINES: dict[str, dict[str, Any]] = {
    "loan_enquiry_gu": {
        "customer_lang": "gu",
        "staff_lang": "en",
        "intent": "loan_enquiry",
        "original": "નમસ્તે, મારે પાંચ લાખનું પર્સનલ લોન જોઈએ છે, EMI કેટલી થશે? મારો PAN છે ABCDE1234F.",
        "translated_en": "Hello, I need a personal loan of five lakh rupees. What would the EMI be? My PAN is ABCDE1234F.",
        "form_seed": {"pan": "ABCDE1234F"},
        "products_discussed": ["Personal loan"],
    },
    "account_opening_gu": {
        "customer_lang": "gu",
        "staff_lang": "en",
        "intent": "account_opening",
        "original": "નમસ્તે, મારે બચત ખાતું ખોલવું છે. મારો મોબાઇલ નંબર 9876543210 છે.",
        "translated_en": "Hello, I would like to open a savings account. My mobile number is 9876543210.",
        "form_seed": {"phone": "9876543210"},
        "products_discussed": ["Savings account"],
    },
    "loan_enquiry_hi": {
        "customer_lang": "hi",
        "staff_lang": "en",
        "intent": "loan_enquiry",
        "original": "नमस्ते, मुझे पाँच लाख का पर्सनल लोन चाहिए, EMI कितनी होगी? मेरा PAN है ABCDE1234F।",
        "translated_en": "Hello, I need a personal loan of five lakh rupees. What would the EMI be? My PAN is ABCDE1234F.",
        "form_seed": {"pan": "ABCDE1234F"},
        "products_discussed": ["Personal loan"],
    },
    "account_opening_ta": {
        "customer_lang": "ta",
        "staff_lang": "en",
        "intent": "account_opening",
        "original": "வணக்கம், சேமிப்பு கணக்கு திறக்க வேண்டும். என் மொபைல் 9876543210.",
        "translated_en": "Hello, I would like to open a savings account. My mobile number is 9876543210.",
        "form_seed": {"phone": "9876543210"},
        "products_discussed": ["Savings account"],
    },
    "card_dispute_en": {
        "customer_lang": "en",
        "staff_lang": "en",
        "intent": "card_dispute",
        "original": "Hi, I need to dispute a charge of ₹4,500 on my debit card from last Friday.",
        "translated_en": "Hi, I need to dispute a charge of ₹4,500 on my debit card from last Friday.",
        "form_seed": {},
        "products_discussed": ["Debit card dispute"],
    },
    "remittance_kn": {
        "customer_lang": "kn",
        "staff_lang": "en",
        "intent": "remittance",
        "original": "ನಮಸ್ಕಾರ, ನನಗೆ ೨೫೦೦೦ ರೂಪಾಯಿ ಬೇರೆ ಬ್ಯಾಂಕ್‌ಗೆ NEFT ಮಾಡಬೇಕು. IFSC ಸಿಕ್ಕಿದೆ.",
        "translated_en": "Hello, I need to send ₹25,000 to another bank via NEFT. I have the IFSC code.",
        "form_seed": {},
        "products_discussed": ["NEFT remittance"],
    },
    "locker_te": {
        "customer_lang": "te",
        "staff_lang": "en",
        "intent": "locker",
        "original": "నమస్కారం, నాకు లాకర్ కావాలి. చిన్న సైజు ఉందా?",
        "translated_en": "Hello, I would like to take a locker. Do you have a small size available?",
        "form_seed": {},
        "products_discussed": ["Safe deposit locker"],
    },
}


# ---------------------------------------------------------------------------
# 2. Phrasebook for word/phrase-level translation of free-text inputs
# ---------------------------------------------------------------------------

# Used both to translate staff replies into the customer language and to give
# basic translations for customer text fallback input. Keys are normalised
# (lowercased, punctuation-stripped) source phrases; values are full target
# phrases. We try exact match first, then longest-substring substitution.

# Staff (English) → Customer language banking-phrasebook
EN_TO_HI: dict[str, str] = {
    "hello": "नमस्ते",
    "welcome": "स्वागत है",
    "thank you": "धन्यवाद",
    "please": "कृपया",
    "yes": "हाँ",
    "no": "नहीं",
    # Full sentence templates — matched first because of longest-prefix sort.
    "i will help you with account opening. may i verify your mobile number linked to your aadhaar":
        "मैं आपकी खाता खोलने में सहायता करूँगा। क्या मैं आपके आधार से जुड़ा मोबाइल नंबर सत्यापित कर सकता हूँ",
    "i will help you with account opening": "मैं आपकी खाता खोलने में सहायता करूँगा",
    "i will help you with the loan enquiry. the indicative emi for five lakh over 5 years is around":
        "मैं आपकी ऋण पूछताछ में सहायता करूँगा। पाँच लाख के लिए 5 साल की संकेतक EMI लगभग है",
    "i will help you with the loan enquiry": "मैं आपकी ऋण पूछताछ में सहायता करूँगा",
    "i will help you with your card dispute": "मैं आपके कार्ड विवाद में सहायता करूँगा",
    "i will help you with the locker": "मैं लॉकर हेतु आपकी सहायता करूँगा",
    "i will help you": "मैं आपकी सहायता करूँगा",
    "could you tell me which type of loan you are considering — personal, home, vehicle, gold, or business":
        "क्या आप बता सकते हैं कि कौन-सा लोन चाहिए — पर्सनल, होम, वाहन, गोल्ड या बिज़नेस",
    "would you like a savings, current, salary, minor, or joint account":
        "क्या आप बचत, चालू, सैलरी, नाबालिग या संयुक्त खाता चाहते हैं",
    "is this an unauthorised charge, a duplicate, a service you didn't receive, or a lost / stolen card":
        "क्या यह अनधिकृत शुल्क है, डुप्लिकेट है, सेवा नहीं मिली है, या कार्ड खो/चोरी हुआ है",
    "would you like to send this as neft, rtgs, imps, or is it a foreign remittance":
        "क्या आप यह NEFT, RTGS, IMPS से भेजना चाहते हैं या यह विदेशी प्रेषण है",
    "may i have your pan number": "क्या मैं आपका PAN नंबर ले सकता हूँ",
    "may i have your aadhaar number": "क्या मैं आपका आधार नंबर ले सकता हूँ",
    "may i verify your mobile number": "क्या मैं आपका मोबाइल नंबर सत्यापित कर सकता हूँ",
    "please share your mobile number": "कृपया अपना मोबाइल नंबर बताएँ",
    "for a personal loan of five lakh the indicative emi": "पाँच लाख के पर्सनल लोन के लिए संकेतक EMI",
    "the indicative emi is around": "संकेतक EMI लगभग है",
    "final rate depends on bank credit policy": "अंतिम दर बैंक की क्रेडिट नीति पर निर्भर है",
    "this is not a sanction letter": "यह स्वीकृति पत्र नहीं है",
    "for a savings account we need kyc documents": "बचत खाते के लिए हमें KYC दस्तावेज़ चाहिए",
    "do you have aadhaar and pan": "क्या आपके पास आधार और PAN है",
    "we will hotlist the card immediately": "हम कार्ड को तुरंत हॉटलिस्ट कर देंगे",
    "i have raised the dispute": "मैंने विवाद दर्ज कर दिया है",
    "expected resolution is within 7 to 10 working days": "समाधान सामान्यतः 7 से 10 कार्य दिवसों में होता है",
    "your reference number is": "आपका संदर्भ नंबर है",
    "please confirm the beneficiary name and ifsc": "कृपया लाभार्थी का नाम और IFSC पुष्टि करें",
    "charges for neft will be as per schedule": "NEFT शुल्क अनुसूची के अनुसार लागू होंगे",
    "small locker is available": "छोटा लॉकर उपलब्ध है",
    "annual rent and security deposit apply": "वार्षिक किराया और सुरक्षा जमा लागू होगा",
    "may i help you with anything else": "क्या मैं आपकी और किसी सहायता कर सकता हूँ",
    "please wait for a moment": "कृपया एक क्षण प्रतीक्षा करें",
    "account opening": "खाता खोलना",
    "mobile number": "मोबाइल नंबर",
    "aadhaar": "आधार",
}

EN_TO_TA: dict[str, str] = {
    "hello": "வணக்கம்",
    "welcome": "வரவேற்கிறேன்",
    "thank you": "நன்றி",
    "please": "தயவுசெய்து",
    "yes": "ஆம்",
    "no": "இல்லை",
    "i will help you": "நான் உங்களுக்கு உதவுகிறேன்",
    "for a savings account we need kyc documents": "சேமிப்பு கணக்கிற்கு KYC ஆவணங்கள் தேவை",
    "do you have aadhaar and pan": "உங்களிடம் ஆதார் மற்றும் PAN உள்ளதா",
    "please share your mobile number": "தயவுசெய்து உங்கள் மொபைல் எண்ணைப் பகிரவும்",
    "may i help you with anything else": "வேறு ஏதேனும் உதவி வேண்டுமா",
    "the indicative emi is around": "சுட்டிக்காட்டும் EMI சுமார்",
    "this is not a sanction letter": "இது அனுமதி கடிதம் அல்ல",
}

EN_TO_KN: dict[str, str] = {
    "hello": "ನಮಸ್ಕಾರ",
    "thank you": "ಧನ್ಯವಾದ",
    "please": "ದಯವಿಟ್ಟು",
    "yes": "ಹೌದು",
    "no": "ಇಲ್ಲ",
    "i will help you": "ನಾನು ನಿಮಗೆ ಸಹಾಯ ಮಾಡುತ್ತೇನೆ",
    "please confirm the beneficiary name and ifsc": "ದಯವಿಟ್ಟು ಫಲಾನುಭವಿಯ ಹೆಸರು ಮತ್ತು IFSC ಖಚಿತಪಡಿಸಿ",
    "charges for neft will be as per schedule": "NEFT ಶುಲ್ಕಗಳು ವೇಳಾಪಟ್ಟಿಯಂತೆ ಅನ್ವಯವಾಗುತ್ತವೆ",
}

EN_TO_TE: dict[str, str] = {
    "hello": "నమస్కారం",
    "thank you": "ధన్యవాదాలు",
    "please": "దయచేసి",
    "i will help you": "నేను మీకు సహాయం చేస్తాను",
    "small locker is available": "చిన్న లాకర్ అందుబాటులో ఉంది",
    "annual rent and security deposit apply": "వార్షిక అద్దె మరియు భద్రతా డిపాజిట్ వర్తిస్తుంది",
}

EN_TO_BN: dict[str, str] = {
    "hello": "নমস্কার",
    "thank you": "ধন্যবাদ",
    "please": "অনুগ্রহ করে",
    "i will help you": "আমি আপনাকে সাহায্য করব",
}

EN_TO_MR: dict[str, str] = {
    "hello": "नमस्कार",
    "thank you": "धन्यवाद",
    "please": "कृपया",
    "i will help you": "मी तुमची मदत करेन",
}

EN_TO_GU: dict[str, str] = {
    "hello": "નમસ્તે",
    "welcome": "સ્વાગત છે",
    "thank you": "આભાર",
    "please": "કૃપા કરીને",
    "yes": "હા",
    "no": "ના",
    "i will help you with account opening. may i verify your mobile number linked to your aadhaar":
        "હું તમને ખાતું ખોલવામાં મદદ કરીશ. શું હું તમારા આધાર સાથે જોડાયેલ મોબાઇલ નંબરની ચકાસણી કરી શકું",
    "i will help you with account opening": "હું તમને ખાતું ખોલવામાં મદદ કરીશ",
    "i will help you with the loan enquiry. the indicative emi for five lakh over 5 years is around":
        "હું તમને લોન પૂછપરછમાં મદદ કરીશ. પાંચ લાખ માટે 5 વર્ષની સૂચક EMI આશરે છે",
    "i will help you with the loan enquiry": "હું તમને લોન પૂછપરછમાં મદદ કરીશ",
    "i will help you with your card dispute": "હું તમારા કાર્ડ વિવાદમાં મદદ કરીશ",
    "i will help you": "હું તમારી મદદ કરીશ",
    "could you tell me which type of loan you are considering — personal, home, vehicle, gold, or business":
        "શું તમે કહી શકો કે કયા પ્રકારનું લોન જોઈએ — પર્સનલ, હોમ, વાહન, ગોલ્ડ કે બિઝનેસ",
    "would you like a savings, current, salary, minor, or joint account":
        "શું તમે બચત, ચાલુ, પગાર, સગીર કે સંયુક્ત ખાતું ઇચ્છો છો",
    "may i have your pan number": "શું હું તમારો PAN નંબર લઈ શકું",
    "may i have your aadhaar number": "શું હું તમારો આધાર નંબર લઈ શકું",
    "may i verify your mobile number": "શું હું તમારો મોબાઇલ નંબર ચકાસી શકું",
    "please share your mobile number": "કૃપા કરીને તમારો મોબાઇલ નંબર શેર કરો",
    "the indicative emi is around": "સૂચક EMI આશરે છે",
    "final rate depends on bank credit policy": "અંતિમ દર બેંકની ક્રેડિટ નીતિ પર આધાર રાખે છે",
    "this is not a sanction letter": "આ મંજૂરી પત્ર નથી",
    "for a savings account we need kyc documents": "બચત ખાતા માટે અમને KYC દસ્તાવેજો જોઈએ",
    "do you have aadhaar and pan": "શું તમારી પાસે આધાર અને PAN છે",
    "we will hotlist the card immediately": "અમે કાર્ડને તરત જ હોટલિસ્ટ કરી દઈશું",
    "i have raised the dispute": "મેં વિવાદ નોંધાવ્યો છે",
    "expected resolution is within 7 to 10 working days": "ઉકેલ સામાન્ય રીતે 7 થી 10 કાર્યકારી દિવસોમાં થાય છે",
    "your reference number is": "તમારો સંદર્ભ નંબર છે",
    "may i help you with anything else": "શું હું તમને બીજી કોઈ મદદ કરી શકું",
    "please wait for a moment": "કૃપા કરીને એક ક્ષણ રાહ જુઓ",
}

EN_TO_ML: dict[str, str] = {
    "hello": "നമസ്കാരം",
    "thank you": "നന്ദി",
    "please": "ദയവായി",
    "i will help you": "ഞാൻ സഹായിക്കാം",
}

EN_TO_PA: dict[str, str] = {
    "hello": "ਸਤ ਸ੍ਰੀ ਅਕਾਲ",
    "thank you": "ਧੰਨਵਾਦ",
    "please": "ਕਿਰਪਾ ਕਰਕੇ",
    "i will help you": "ਮੈਂ ਤੁਹਾਡੀ ਮਦਦ ਕਰਾਂਗਾ",
}

EN_TO_OR: dict[str, str] = {
    "hello": "ନମସ୍କାର",
    "thank you": "ଧନ୍ୟବାଦ",
    "please": "ଦୟାକରି",
    "i will help you": "ମୁଁ ଆପଣଙ୍କୁ ସାହାଯ୍ୟ କରିବି",
}

# Reverse phrasebook: customer language → English. Built from a smaller set
# of the most common banking utterances we expect from a customer.
HI_TO_EN: dict[str, str] = {
    "नमस्ते": "Hello",
    "धन्यवाद": "Thank you",
    "हाँ": "Yes",
    "नहीं": "No",
    "मुझे पर्सनल लोन चाहिए": "I would like a personal loan",
    "मुझे लोन चाहिए": "I want a loan",
    "मुझे खाता खोलना है": "I would like to open an account",
    "बचत खाता": "savings account",
    "चालू खाता": "current account",
    "पाँच लाख": "five lakh",
    "दस लाख": "ten lakh",
    "ईएमआई कितनी होगी": "what would the EMI be",
    "emi कितनी होगी": "what would the EMI be",
    "मेरा pan है": "my PAN is",
    "मेरा आधार है": "my Aadhaar is",
    "मेरा मोबाइल है": "my mobile number is",
    "कार्ड खो गया": "my card is lost",
    "कार्ड पर शुल्क लगा है": "there is a charge on my card",
    "लॉकर चाहिए": "I want a locker",
    "neft करना है": "I need to do an NEFT",
    "पैसा भेजना है": "I need to send money",
}

TA_TO_EN: dict[str, str] = {
    "வணக்கம்": "Hello",
    "நன்றி": "Thank you",
    "ஆம்": "Yes",
    "இல்லை": "No",
    "சேமிப்பு கணக்கு": "savings account",
    "சேமிப்பு கணக்கு திறக்க வேண்டும்": "I want to open a savings account",
    "என் மொபைல்": "my mobile number is",
    "கடன் வேண்டும்": "I want a loan",
    "லாக்கர் வேண்டும்": "I want a locker",
}

KN_TO_EN: dict[str, str] = {
    "ನಮಸ್ಕಾರ": "Hello",
    "ಧನ್ಯವಾದ": "Thank you",
    "ಸಾಲ ಬೇಕು": "I need a loan",
    "ಉಳಿತಾಯ ಖಾತೆ": "savings account",
    "NEFT ಮಾಡಬೇಕು": "I need to do an NEFT",
    "ಲಾಕರ್ ಬೇಕು": "I want a locker",
}

TE_TO_EN: dict[str, str] = {
    "నమస్కారం": "Hello",
    "ధన్యవాదాలు": "Thank you",
    "లాకర్ కావాలి": "I want a locker",
    "చిన్న సైజు ఉందా": "Is a small size available",
    "ఖాతా తెరవాలి": "I want to open an account",
}

GU_TO_EN: dict[str, str] = {
    "નમસ્તે": "Hello",
    "આભાર": "Thank you",
    "હા": "Yes",
    "ના": "No",
    "મારે પર્સનલ લોન જોઈએ છે": "I would like a personal loan",
    "મારે લોન જોઈએ છે": "I want a loan",
    "મારે ખાતું ખોલવું છે": "I would like to open an account",
    "બચત ખાતું": "savings account",
    "ચાલુ ખાતું": "current account",
    "પાંચ લાખ": "five lakh",
    "દસ લાખ": "ten lakh",
    "emi કેટલી થશે": "what would the EMI be",
    "મારો pan છે": "my PAN is",
    "મારો આધાર છે": "my Aadhaar is",
    "મારો મોબાઇલ છે": "my mobile number is",
    "કાર્ડ ખોવાયું": "my card is lost",
    "લોકર જોઈએ": "I want a locker",
    "neft કરવું છે": "I need to do an NEFT",
    "પૈસા મોકલવા છે": "I need to send money",
}

PHRASEBOOK: dict[tuple[str, str], dict[str, str]] = {
    ("en", "hi"): EN_TO_HI,
    ("en", "ta"): EN_TO_TA,
    ("en", "kn"): EN_TO_KN,
    ("en", "te"): EN_TO_TE,
    ("en", "bn"): EN_TO_BN,
    ("en", "mr"): EN_TO_MR,
    ("en", "gu"): EN_TO_GU,
    ("en", "ml"): EN_TO_ML,
    ("en", "pa"): EN_TO_PA,
    ("en", "or"): EN_TO_OR,
    ("hi", "en"): HI_TO_EN,
    ("ta", "en"): TA_TO_EN,
    ("kn", "en"): KN_TO_EN,
    ("te", "en"): TE_TO_EN,
    ("gu", "en"): GU_TO_EN,
}


_PUNCT_RE = re.compile(r"[।,.!?;:\"'`(){}\[\]]+")


def _norm(s: str) -> str:
    return _PUNCT_RE.sub("", (s or "").strip().lower())


def demo_translate(text: str, source_lang: str, target_lang: str) -> str:
    """Phrasebook-based translation. Preserves identifiers (PAN, phone, amounts).

    Falls back to passing the text through with a small `[demo]` marker stripped
    so the staff at least sees the *original* without scary error strings.
    """
    if not text or source_lang == target_lang:
        return text

    # 1. Scenario-line exact match — needed because the demo "inject scenario"
    #    sends a full Hindi/Tamil sentence we want a clean English line for.
    for sc in SCENARIO_LINES.values():
        if sc["customer_lang"] == source_lang and text.strip() == sc["original"].strip():
            return sc["translated_en"] if target_lang == "en" else text

    book = PHRASEBOOK.get((source_lang, target_lang))
    if not book:
        return text  # passthrough — caller marks as untranslated

    # 2. Exact (normalised) match
    norm_text = _norm(text)
    for src_phrase, tgt_phrase in book.items():
        if _norm(src_phrase) == norm_text:
            return _restore_identifiers(text, tgt_phrase)

    # 3. Substring substitution (longest-first to avoid partial collisions)
    out = text
    for src_phrase in sorted(book.keys(), key=len, reverse=True):
        if _norm(src_phrase) and _norm(src_phrase) in _norm(out):
            # use case-insensitive replace on original casing
            pat = re.compile(re.escape(src_phrase), re.IGNORECASE)
            out = pat.sub(book[src_phrase], out)

    return out


_IDENTIFIER_RE = re.compile(
    r"\b("
    r"[A-Z]{5}[0-9]{4}[A-Z]"          # PAN
    r"|\d{4}\s?\d{4}\s?\d{4}"         # Aadhaar
    r"|(?:\+91[\s-]?)?[6-9]\d{9}"     # phone
    r"|[A-Z]{4}0[A-Z0-9]{6}"          # IFSC
    r"|₹[\d,]+"                       # rupee amounts
    r"|\d+\s*(?:lakh|crore|rupees|rs)\.?"  # written amounts
    r")\b",
    re.I,
)


def _restore_identifiers(original: str, translated: str) -> str:
    """If the translation dropped PAN/Aadhaar/phone/amounts, append them.

    Keeps numeric identifiers visible even when the phrasebook entry was a generic
    greeting that wouldn't naturally include them.
    """
    ids = _IDENTIFIER_RE.findall(original)
    if not ids:
        return translated
    missing = [i for i in ids if i and i not in translated]
    if not missing:
        return translated
    return f"{translated} ({', '.join(missing)})"


# ---------------------------------------------------------------------------
# 3. Heuristic intent classifier
# ---------------------------------------------------------------------------

INTENT_KEYWORDS: dict[str, list[str]] = {
    "loan_enquiry": [
        "loan", "emi", "personal loan", "home loan", "interest rate",
        "लोन", "ईएमआई", "ब्याज", "पर्सनल लोन", "होम लोन", "ऋण",
        "கடன்", "ಸಾಲ", "రుణం",
        "લોન", "પર્સનલ લોન", "હોમ લોન",
    ],
    "account_opening": [
        "open account", "savings account", "current account", "kyc", "account opening",
        "खाता खोलना", "बचत खाता", "चालू खाता", "नया खाता",
        "சேமிப்பு கணக்கு", "கணக்கு திறக்க",
        "ಉಳಿತಾಯ ಖಾತೆ", "ఖాతా తెరవాలి",
        "બચત ખાતું", "ખાતું ખોલવું", "ચાલુ ખાતું",
    ],
    "card_dispute": [
        "dispute", "unauthorised", "unauthorized", "fraud", "lost card", "stolen card", "chargeback",
        "कार्ड", "विवाद", "खो गया", "धोखाधड़ी",
        "કાર્ડ", "વિવાદ", "ખોવાયું",
    ],
    "remittance": [
        "neft", "rtgs", "imps", "transfer", "remit", "wire", "swift", "ifsc", "beneficiary",
        "पैसा भेजना", "भेजना है", "ट्रांसफर", "लाभार्थी",
        "પૈસા મોકલવા", "મોકલવા છે",
    ],
    "locker": [
        "locker", "safe deposit",
        "लॉकर",
        "லாக்கர்", "ಲಾಕರ್", "లాకర్",
        "લોકર",
    ],
}


def classify_intent(text: str) -> tuple[str, float]:
    """Cheap keyword-based intent classifier. Returns (intent, confidence)."""
    if not text:
        return "generic", 0.3
    lowered = text.lower()
    best_intent = "generic"
    best_score = 0
    for intent, kws in INTENT_KEYWORDS.items():
        score = sum(1 for k in kws if k.lower() in lowered)
        if score > best_score:
            best_intent = intent
            best_score = score
    confidence = 0.5 if best_score == 0 else min(0.95, 0.65 + 0.1 * best_score)
    return best_intent, confidence


# ---------------------------------------------------------------------------
# 4. Demo copilot enrichment
# ---------------------------------------------------------------------------

_TALKING_POINTS: dict[str, dict[str, list[str]]] = {
    "loan_enquiry": {
        "en": [
            "Confirm the loan purpose, amount, and preferred tenure before discussing rates.",
            "Share an illustrative EMI only — final sanction is subject to underwriting.",
            "Capture consent for credit bureau pull if the customer wants to proceed.",
        ],
        "hi": [
            "दर पर चर्चा से पहले ऋण उद्देश्य, राशि और अवधि की पुष्टि करें।",
            "केवल संकेतक EMI साझा करें — अंतिम स्वीकृति अंडरराइटिंग पर निर्भर है।",
            "यदि ग्राहक आगे बढ़ना चाहे तो क्रेडिट ब्यूरो पुल हेतु सहमति लें।",
        ],
    },
    "account_opening": {
        "en": [
            "Confirm the account variant the customer wants (savings / current / minor).",
            "Verify KYC documents — Aadhaar + PAN is the most common combination.",
            "Explain minimum balance, schedule of charges, and nominee requirement.",
        ],
        "hi": [
            "ग्राहक द्वारा चाहा गया खाता प्रकार पुष्टि करें (बचत / चालू / नाबालिग)।",
            "KYC दस्तावेज़ सत्यापित करें — आधार + PAN सबसे सामान्य संयोजन है।",
            "न्यूनतम शेष, शुल्क अनुसूची और नामांकन आवश्यकता समझाएँ।",
        ],
    },
    "card_dispute": {
        "en": [
            "Confirm card possession and last recognised transaction.",
            "Offer to hotlist the card immediately if fraud is suspected.",
            "Do not promise a chargeback outcome — log the dispute with reference number.",
        ],
        "hi": [
            "कार्ड कब्ज़ा और अंतिम मान्य लेनदेन की पुष्टि करें।",
            "धोखाधड़ी के संदेह पर तुरंत कार्ड हॉटलिस्ट करने का सुझाव दें।",
            "चार्जबैक का वादा न करें — संदर्भ नंबर के साथ विवाद दर्ज करें।",
        ],
    },
    "remittance": {
        "en": [
            "Confirm beneficiary name, account number, and IFSC against the mandate.",
            "Quote applicable charges per the schedule before initiating the transfer.",
            "For outward remittance, validate purpose code and LRS limit if relevant.",
        ],
        "hi": [
            "लाभार्थी का नाम, खाता संख्या और IFSC जनादेश से मिलाकर पुष्टि करें।",
            "अंतरण आरंभ करने से पहले लागू शुल्क अनुसूची के अनुसार बताएँ।",
            "विदेशी प्रेषण हेतु प्रयोजन कोड और LRS सीमा सत्यापित करें।",
        ],
    },
    "locker": {
        "en": [
            "Check locker availability by size and confirm waitlist position if any.",
            "Explain annual rent, security deposit, and dual-key operation policy.",
            "Capture nominee details and joint operation preferences upfront.",
        ],
        "hi": [
            "आकार के अनुसार लॉकर उपलब्धता जाँचें और प्रतीक्षा सूची की स्थिति बताएँ।",
            "वार्षिक किराया, सुरक्षा जमा और दो-कुंजी संचालन नीति समझाएँ।",
            "नामांकन विवरण और संयुक्त संचालन वरीयता पहले ही दर्ज करें।",
        ],
    },
    "generic": {
        "en": [
            "Greet the customer and confirm their preferred language.",
            "Ask for the purpose of visit and verify identity before sharing PII.",
            "Document the outcome and any follow-up commitments before close.",
        ],
        "hi": [
            "ग्राहक का अभिवादन करें और पसंदीदा भाषा पुष्टि करें।",
            "उद्देश्य पूछें और PII साझा करने से पहले पहचान सत्यापित करें।",
            "समापन से पहले परिणाम और अनुवर्ती प्रतिबद्धताएँ दर्ज करें।",
        ],
    },
}


_DISAMBIG: dict[str, list[dict[str, Any]]] = {
    "loan_enquiry": [
        {
            "dimension": "Loan type",
            "choices": ["Personal", "Home", "Vehicle", "Gold", "Business"],
            "staff_prompt": "Could you tell me which type of loan you are considering — personal, home, vehicle, gold, or business?",
        },
    ],
    "account_opening": [
        {
            "dimension": "Account variant",
            "choices": ["Savings", "Current", "Salary", "Minor", "Joint"],
            "staff_prompt": "Would you like a savings, current, salary, minor, or joint account?",
        },
    ],
    "card_dispute": [
        {
            "dimension": "Dispute type",
            "choices": ["Unauthorised charge", "Duplicate charge", "Service not received", "Card lost / stolen"],
            "staff_prompt": "Is this an unauthorised charge, a duplicate, a service you didn't receive, or a lost / stolen card?",
        },
    ],
    "remittance": [
        {
            "dimension": "Mode",
            "choices": ["NEFT", "RTGS", "IMPS", "Inward / Outward FX"],
            "staff_prompt": "Would you like to send this as NEFT, RTGS, IMPS, or is it a foreign remittance?",
        },
    ],
}


def _hindi_summary_for_intent(intent: str) -> str:
    return {
        "loan_enquiry": "ग्राहक ने ऋण के बारे में पूछा। दर और EMI केवल संकेतक हैं।",
        "account_opening": "ग्राहक नया खाता खोलना चाहते हैं। KYC आवश्यक है।",
        "card_dispute": "ग्राहक ने कार्ड पर शुल्क विवाद दर्ज किया।",
        "remittance": "ग्राहक को धन प्रेषण की आवश्यकता है।",
        "locker": "ग्राहक लॉकर लेना चाहते हैं।",
        "generic": "ग्राहक सहायता हेतु शाखा में आए।",
    }.get(intent, "ग्राहक से बातचीत।")


def _gujarati_summary_for_intent(intent: str) -> str:
    return {
        "loan_enquiry": "ગ્રાહકે લોન વિશે પૂછપરછ કરી. દર અને EMI માત્ર સૂચક છે.",
        "account_opening": "ગ્રાહક નવું ખાતું ખોલવા માંગે છે. KYC આવશ્યક છે.",
        "card_dispute": "ગ્રાહકે કાર્ડ પર શુલ્ક વિવાદ નોંધાવ્યો.",
        "remittance": "ગ્રાહકને પૈસા મોકલવાની જરૂર છે.",
        "locker": "ગ્રાહક લોકર લેવા માંગે છે.",
        "generic": "ગ્રાહક સહાય માટે શાખામાં આવ્યા.",
    }.get(intent, "ગ્રાહક સાથે વાતચીત.")


def demo_enrich(
    *,
    customer_text: str,
    asr_confidence: float,
    staff_lang: str,
    customer_lang: str,
) -> dict[str, Any]:
    """Build a plausible copilot enrichment from a customer turn."""
    intent, ic = classify_intent(customer_text)
    tp_block = _TALKING_POINTS.get(intent, _TALKING_POINTS["generic"])
    talking_points = tp_block.get(staff_lang) or tp_block.get("en") or []

    risk_flags: list[dict[str, str]] = []
    lower = customer_text.lower()
    if any(x in lower for x in ("guaranteed", "sure approval", "100% approval", "गारंटी")):
        risk_flags.append({"level": "high", "reason": "Customer expects a guaranteed outcome — set expectations."})
    if any(x in lower for x in ("otp", "ओटीपी", "password", "पासवर्ड")):
        risk_flags.append({"level": "high", "reason": "OTP / password mentioned — never repeat aloud."})

    code_mix = None
    has_latin = bool(re.search(r"[A-Za-z]", customer_text))
    has_devanagari = bool(re.search(r"[ऀ-ॿ]", customer_text))
    if has_latin and has_devanagari:
        code_mix = "Code-mixed Hindi-English detected — confirm key terms before recording."

    out: dict[str, Any] = {
        "intent": intent,
        "intent_confidence": round(ic, 2),
        "risk_flags": risk_flags,
        "talking_points_staff_lang": talking_points,
        "disambiguation_options": _DISAMBIG.get(intent, []),
        "code_mixing_note": code_mix,
    }
    if asr_confidence < 0.5:
        out["low_confidence_fallback"] = (
            "Confidence is low — please ask the customer to repeat slowly in their preferred language."
        )
    return out


# ---------------------------------------------------------------------------
# 5. Demo form extraction (extends the existing regex heuristics)
# ---------------------------------------------------------------------------

_NAME_PATTERNS = [
    re.compile(r"my name is ([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})"),
    re.compile(r"मेरा नाम ([ऀ-ॿ]+(?:\s+[ऀ-ॿ]+){0,3}) है"),
    re.compile(r"என் பெயர் ([஀-௿a-zA-Z]+(?:\s+[஀-௿a-zA-Z]+){0,3})"),
    re.compile(r"ನನ್ನ ಹೆಸರು ([ಀ-೿a-zA-Z]+(?:\s+[ಀ-೿a-zA-Z]+){0,3})"),
    re.compile(r"నా పేరు ([ఀ-౿a-zA-Z]+(?:\s+[ఀ-౿a-zA-Z]+){0,3})"),
]

_ADDRESS_HINTS = [
    re.compile(r"i (?:stay|live) at ([^\.\n]{4,80})", re.I),
    re.compile(r"मैं ([^।\n]{4,80}) में रहता", re.I),
]


def demo_form_extract(text: str) -> dict[str, Any]:
    """Adds full_name / address detection on top of llm_bank.heuristic_extract."""
    out: dict[str, Any] = {}
    for pat in _NAME_PATTERNS:
        m = pat.search(text)
        if m:
            out["full_name"] = m.group(1).strip()
            break
    for pat in _ADDRESS_HINTS:
        m = pat.search(text)
        if m:
            out["address"] = m.group(1).strip()
            break
    return out


# ---------------------------------------------------------------------------
# 6. Demo bilingual summary
# ---------------------------------------------------------------------------

_SUMMARY_TEMPLATES_EN: dict[str, str] = {
    "loan_enquiry": (
        "Customer enquired about a loan facility. Staff shared indicative EMI guidance "
        "and clarified that final sanction is subject to underwriting and credit policy."
    ),
    "account_opening": (
        "Customer requested to open a new account. Staff explained KYC requirements, "
        "minimum balance, and schedule of charges; nominee details were discussed."
    ),
    "card_dispute": (
        "Customer raised a card transaction dispute. Staff confirmed card possession, "
        "offered to hotlist if needed, and logged the dispute reference for TAT tracking."
    ),
    "remittance": (
        "Customer wanted to remit funds. Staff verified beneficiary details, explained "
        "applicable charges, and confirmed cut-off timings for the chosen mode."
    ),
    "locker": (
        "Customer enquired about a locker. Staff checked availability by size and "
        "explained rent, security deposit, and dual-key operating policy."
    ),
    "generic": (
        "Customer visited the branch for service. Staff confirmed identity, addressed "
        "the query, and documented next steps."
    ),
}


def demo_summary(
    *,
    turns: list[dict[str, Any]],
    customer_lang: str,
    staff_lang: str,
    metrics: dict[str, Any] | None,
) -> dict[str, Any]:
    """Heuristic bilingual summary from the live turns."""
    joined_customer = " ".join(
        (t.get("original") or "") for t in turns if t.get("role") == "customer"
    )
    intent, _ = classify_intent(joined_customer or " ".join(t.get("original", "") for t in turns))

    products: list[str] = []
    if intent == "loan_enquiry":
        products = ["Personal loan (indicative)"]
    elif intent == "account_opening":
        products = ["Savings / current account"]
    elif intent == "card_dispute":
        products = ["Debit / credit card dispute"]
    elif intent == "remittance":
        products = ["NEFT / RTGS / IMPS"]
    elif intent == "locker":
        products = ["Safe deposit locker"]

    summary_en = _SUMMARY_TEMPLATES_EN.get(intent, _SUMMARY_TEMPLATES_EN["generic"])
    if customer_lang == "hi":
        summary_customer = _hindi_summary_for_intent(intent)
    elif customer_lang == "gu":
        summary_customer = _gujarati_summary_for_intent(intent)
    else:
        summary_customer = summary_en

    # Pick first customer + first staff turn as attributed quotes.
    quotes: list[dict[str, str]] = []
    for t in turns:
        if t.get("role") == "customer" and t.get("original"):
            quotes.append({"role": "customer", "excerpt": str(t["original"])[:160]})
            break
    for t in turns:
        if t.get("role") == "staff" and t.get("original"):
            quotes.append({"role": "staff", "excerpt": str(t["original"])[:160]})
            break

    action_items: list[str] = []
    if intent == "loan_enquiry":
        action_items = [
            "Capture income proof and consent for bureau pull before formal application.",
            "Share illustrative EMI calculation in writing on customer request.",
        ]
    elif intent == "account_opening":
        action_items = [
            "Collect KYC documents and process CKYC lookup.",
            "Capture nominee details and obtain signature on account opening form.",
        ]
    elif intent == "card_dispute":
        action_items = [
            "Log dispute reference in CRM and share with customer over SMS.",
            "Advise hotlisting if not already done.",
        ]

    kpi_note = ""
    if metrics:
        kpi_note = (
            f"Session duration {metrics.get('session_seconds', 0)}s across "
            f"{metrics.get('total_turns', 0)} turns; "
            f"{metrics.get('low_confidence_segments', 0)} low-confidence segment(s)."
        )

    return {
        "summary_staff_lang": summary_en,
        "summary_customer_lang": summary_customer,
        "action_items": action_items,
        "products_discussed": products,
        "open_questions": [],
        "compliance_notes": [
            "Indicative figures only — no commitments made.",
            "PII redacted before storage.",
        ],
        "attributed_quotes": quotes,
        "session_kpis_comment": kpi_note or "Session completed.",
    }
