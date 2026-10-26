import re

PII_PATTERNS = {
 'GSTIN': re.compile(r'\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]\b', re.I),
 'PAN': re.compile(r'\b[A-Z]{5}\d{4}[A-Z]\b', re.I),
 'IFSC': re.compile(r'\b[A-Z]{4}0[A-Z0-9]{6}\b', re.I),
 'BANK_AC': re.compile(r'\b(?:A/C|Account\s*(?:No\.?|Number)|Acct(?:\s*No\.?)?)[\s:#-]*(\d{9,18})\b', re.I),
 'AADHAAR': re.compile(r'\b[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}\b'),
 'MOBILE': re.compile(r'(?<!\w)(?:\+91[ -]?)?[6-9]\d{9}\b'),
 'EMAIL': re.compile(r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b'),
}

def scrub_pii_before_llm(raw_text: str) -> tuple[str,dict[str,str],int]:
    mapping = {}
    text = raw_text
    for label, pattern in PII_PATTERNS.items():
        def replace(match):
            value = match.group(1) if label=='BANK_AC' else match.group(0)
            existing = next((key for key, secret in mapping.items() if secret == value), None)
            if existing:
                return match.group(0).replace(value,existing) if label=='BANK_AC' else existing
            key = f'[REDACTED_{label}_{len(mapping)+1}]'
            mapping[key] = value
            return match.group(0).replace(value,key) if label=='BANK_AC' else key
        text = pattern.sub(replace, text)
    # The same identifier may also occur without its original field label.
    for key,value in sorted(mapping.items(),key=lambda item:len(item[1]),reverse=True):
        text=text.replace(value,key)
    return text, mapping, len(mapping)
