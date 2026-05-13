"""Banking task specialization: few-shot patterns for JSON copilot outputs (instruction-tuned style)."""

from __future__ import annotations

# Appended to system context so any compatible chat model behaves like a domain-tuned assistant.
BANKING_JSON_FEW_SHOTS = """
## Banking JSON examples (follow structure and tone; adapt to live transcript)

Example A — loan enquiry (Hinglish customer, English staff bullets):
User context: Customer said they need 5 lakh personal loan and EMI.
JSON:
{"intent":"loan_enquiry","intent_confidence":0.88,"risk_flags":[{"level":"medium","reason":"EMI discussed — avoid guaranteed approval wording"}],"talking_points_staff_lang":["I can share an illustrative EMI based on standard amortisation; final terms depend on underwriting.","May I confirm your employment type and gross monthly income band?","We will need consent before a bureau enquiry if you proceed to application."],"disambiguation_options":[{"dimension":"Product","choices":["Personal loan","Gold loan","Top-up home loan"],"staff_prompt":"Are you looking for an unsecured personal loan or a secured option like gold loan?"}],"low_confidence_fallback":null,"code_mixing_note":"Customer mixed Hindi and English numerals; confirm amount in digits on screen."}

Example B — account opening:
JSON:
{"intent":"account_opening","intent_confidence":0.91,"risk_flags":[],"talking_points_staff_lang":["I'll explain savings variants and minimum balance before we proceed.","We will complete KYC per RBI guidelines — please share your OVD.","Nominee details help smooth settlement; may I record nominee name and relationship?"],"disambiguation_options":[{"dimension":"Account type","choices":["Regular savings","Salary","Senior citizen"],"staff_prompt":"Which savings variant fits you — regular, salary-linked, or senior citizen?"}],"low_confidence_fallback":null,"code_mixing_note":null}

Example C — card dispute:
JSON:
{"intent":"card_dispute","intent_confidence":0.85,"risk_flags":[{"level":"high","reason":"Unauthorised txn alleged — follow dispute SOP"}],"talking_points_staff_lang":["I will help log a dispute; timelines follow network rules.","If you did not authorise the txn, we can hotlist after verification.","Please do not share OTP or full card number aloud in the branch hall."],"disambiguation_options":[],"low_confidence_fallback":null,"code_mixing_note":null}

When uncertain, intent_confidence < 0.6 and add disambiguation_options or low_confidence_fallback.
"""
