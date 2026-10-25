import re

PII_PATTERNS = {
 'GSTIN': re.compile(r'\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]\b', re.I),
 'PAN': re.compile(r'\b[A-Z]{5}\d{4}[A-Z]\b', re.I),
 'BANK_AC': re.compile(r'\b(?:A/C|Account\s*(?:No\.?|Number)|Acct)[\s:#-]*\d{9,18}\b', re.I),
 'AADHAAR': re.compile(r'\b[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}\b'),
 'MOBILE': re.compile(r'(?<!\w)(?:\+91[ -]?)?[6-9]\d{9}\b'),
 'EMAIL': re.compile(r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b'),
}

def scrub_pii_before_llm(raw_text: str) -> tuple[str,dict[str,str],int]:
    mapping = {}
    text = raw_text
    for label, pattern in PII_PATTERNS.items():
        def replace(match):
            value = match.group(0)
            existing = next((key for key, secret in mapping.items() if secret == value), None)
            if existing:
                return existing
            key = f'[REDACTED_{label}_{len(mapping)+1}]'
            mapping[key] = value
            return key
        text = pattern.sub(replace, text)
    return text, mapping, len(mapping)
