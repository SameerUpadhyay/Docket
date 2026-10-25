import re
from email.utils import parseaddr
from urllib.parse import urlparse
from app.models.schemas import AuthenticityVerdict, ForensicCheckResult

OFFICIAL_GOV_DOMAINS = {'incometax.gov.in','cpc.incometax.gov.in','tdscpc.gov.in','gst.gov.in','gstn.org.in','cbic.gov.in','icegate.gov.in','mca.gov.in','epfindia.gov.in','shramsuvidha.gov.in','esic.gov.in','esic.nic.in','esic.in','msme.gov.in','udyamregistration.gov.in','dcmsme.gov.in','fssai.gov.in','cpcb.nic.in','parivesh.nic.in'}
DIN = re.compile(r'\b(?:CBIC[- ]?\d{6}[A-Z0-9]{10,14}|ITBA/[A-Z0-9/()\-]{15,60}|DIN[ :\-]+[A-Z0-9/\-]{12,28})',re.I)

def official(domain):
    return domain in OFFICIAL_GOV_DOMAINS or domain.endswith('.gov.in') or domain.endswith('.nic.in')

def run_forensic_authenticity_check(raw_from_header='',auth_results_header='',document_text='',extracted_urls=None,qr_decoded_payloads=None,attachment_names=None, trusted_auth=False):
    name,email = parseaddr(raw_from_header)
    domain = email.lower().rsplit('@',1)[-1] if '@' in email else ''
    claims = bool(re.search(r'\b(income tax|incometax|cgst|sgst|gstn|gst|cbic|epfo|esic|fssai|cyber cell|provident fund)\b',name+' '+document_text[:1200],re.I))
    flags=[]
    score=0
    payload=' '.join([document_text,*(qr_decoded_payloads or []),*(extracted_urls or [])])
    if domain and claims and not official(domain):
        score+=45
        flags.append(f'Lookalike / unofficial sender: {domain}. Confirm the sender independently.')
    match=DIN.search(document_text)
    din=match.group(0) if match else None
    if claims and re.search(r'\b(cgst|cbic|income tax|incometax)\b',document_text,re.I) and not din:
        score+=15
        flags.append('No recognizable central-tax DIN. Check applicability and permitted exceptions; this alone does not establish fraud.')
    for pattern,points,message in [
        (r'upi://pay\?|\b[\w.\-]+@(?:okicici|okaxis|oksbi|okhdfcbank|ybl|ibl|paytm|upi)\b',100,'Payment redirection: private UPI / QR payment payload detected.'),
        (r'\b0x[a-fA-F0-9]{40}\b|\bbc1[a-zA-Z0-9]{25,60}\b',100,'Cryptocurrency payment address detected.'),
        (r'share\s+your\s+(?:otp|password|pin)|enter\s+upi\s+pin|anydesk|teamviewer|rustdesk',90,'Credential or remote-access request detected.'),
        (r'digital\s+arrest|join\s+skype\s+investigation|scan\s+(?:the|this)\s+qr\s+code\s+to\s+(?:pay|settle)',85,'Coercion or scam payment instruction detected.'),
    ]:
        if re.search(pattern,payload,re.I):
            score+=points
            flags.append(message)
    for filename in attachment_names or []:
        if re.search(r'\.(apk|exe|scr|bat|vbs|cmd|msi|iso)$',filename,re.I):
            score+=100
            flags.append('Executable attachment blocked: '+filename)
    for url in (extracted_urls or [])+(qr_decoded_payloads or []):
        host=(urlparse(url).hostname or '').lower()
        if claims and host and not official(host):
            score+=35
            flags.append('External link requires review: '+host)
    # User-supplied Authentication-Results is untrusted. Never treat it as a signature verification.
    dkim=bool(re.search(r'\bdkim=pass\b',auth_results_header,re.I)) if trusted_auth else None
    spf=bool(re.search(r'\bspf=pass\b',auth_results_header,re.I)) if trusted_auth else None
    if trusted_auth and official(domain) and (not dkim or not spf):
        score+=70
        flags.append('Trusted receiving server reports failed mail authentication.')
    score=min(score,100)
    verdict=AuthenticityVerdict.PHISHING_SCAM if score>=70 else AuthenticityVerdict.SUSPICIOUS_UNVERIFIED if claims else AuthenticityVerdict.PRIVATE_LEGAL_NOTICE
    if claims and official(domain) and trusted_auth and dkim and spf and score==0:
        verdict=AuthenticityVerdict.VERIFIED_GOV
    return ForensicCheckResult(verdict=verdict,fraud_risk_score=score,sender_email=email or None,sender_domain=domain or None,dkim_passed=dkim,spf_passed=spf,din_extracted=din,din_format_valid=bool(din),scam_flags=flags,safe_to_process=score<70)
