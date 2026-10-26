"""Cryptographic provenance, separate from forgeable forwarded/header claims."""
import os,re,time,logging
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from app.engines.fraud_guard import official

FORWARDED=re.compile(r'(?:-{3,}\s*Forwarded message\s*-{3,}|Begin forwarded message:)[\s\S]{0,800}?^From:\s*([^\r\n]+)',re.I|re.M)
_SIGNATURE_LOG=logging.Logger('docket.email.signature')
_SIGNATURE_LOG.disabled=True

def _tags(value):
    return {k.strip().lower():v.strip() for item in value.split(';') if '=' in item for k,v in [item.split('=',1)]}

def _aligned(signer,sender): return bool(signer and (sender==signer or sender.endswith('.'+signer)))

def _dns_lookup():
    # Verification fetches DNS TXT keys only; messages never leave this process.
    deadline=time.monotonic()+8; remaining=16
    def lookup(name,timeout=2):
        nonlocal remaining
        remaining-=1
        if remaining<0 or time.monotonic()>=deadline: return None
        try:
            import dns.resolver
            value=name.decode('ascii') if isinstance(name,bytes) else name
            if len(value)>254 or not re.fullmatch(r'[a-zA-Z0-9_.-]+',value): return None
            answers=dns.resolver.resolve(value,'TXT',lifetime=min(2,max(.1,deadline-time.monotonic())))
            return b''.join(answers[0].strings)
        except Exception: return None
    return lookup

def verify_provenance(raw,sender_domain,dnsfunc=None):
    verified=False; arc=False; spf=None; signer=''; notes=[]
    if not raw: return verified,arc,spf,signer,['Original MIME is unavailable; supplied authentication headers are unverified claims.']
    message=BytesParser(policy=policy.default).parsebytes(raw)
    lookup=dnsfunc or _dns_lookup()
    try:
        import dkim
        signatures=message.get_all('DKIM-Signature',[])
        for index,signature in enumerate(signatures[:3]):
            tags=_tags(str(signature)); domain=tags.get('d','').lower()
            if 'l' in tags or not _aligned(domain,sender_domain): continue
            if dkim.DKIM(raw,timeout=2,logger=_SIGNATURE_LOG).verify(idx=index,dnsfunc=lookup):
                verified=True; signer=domain; notes.append('The original MIME has a valid aligned DKIM signature.'); break
        seals=message.get_all('ARC-Seal',[])
        if seals and len(seals)<=5:
            latest=max((_tags(str(value)) for value in seals),key=lambda tags:int(tags.get('i','0')))
            trusted={s.strip().lower() for s in os.getenv('INBOUND_TRUSTED_ARC_SEALERS','google.com').split(',') if s.strip()}
            if latest.get('d','').lower() in trusted and not any('l' in _tags(str(v)) for v in message.get_all('ARC-Message-Signature',[])):
                cv,_,_=dkim.arc_verify(raw,dnsfunc=lookup,timeout=2,logger=_SIGNATURE_LOG)
                if cv==dkim.CV_Pass:
                    for header in message.get_all('ARC-Authentication-Results',[]):
                        if _tags(str(header)).get('i')!=latest.get('i'): continue
                        for result in str(header).split(';'):
                            matched=re.search(r'\bdkim=pass\b.*?\bheader\.(?:d|i)=@?([a-z0-9.-]+)',result,re.I)
                            if matched and _aligned(matched.group(1).lower(),sender_domain):
                                verified=True; arc=True; signer=matched.group(1).lower()
                        if arc:
                            spf=bool(re.search(r'\bspf=pass\b',str(header),re.I))
                            notes.append('An intact ARC chain from a configured trusted sealer attests to aligned original DKIM.')
    except Exception:
        notes.append('Signature checks were unavailable or inconclusive; confirm the sender independently.')
    if not verified: notes.append('Original sender signatures have not been verified. Forwarded text and pass/fail header strings are not proof.')
    return verified,arc,spf,signer,notes

def unwrap_forwarded_email_forensics(message,dnsfunc=None):
    name,outer=parseaddr(message.sender); outer=outer.lower()
    forwarded=FORWARDED.search(message.text)
    original=forwarded.group(1) if forwarded else message.sender
    original_name,email=parseaddr(original); email=email.lower()
    domain=email.rsplit('@',1)[-1] if '@' in email else ''
    verified,arc,spf,signer,notes=verify_provenance(message.raw,domain,dnsfunc)
    if forwarded:
        # A forwarder's valid signature does not authenticate quoted From text.
        verified=False; arc=False; spf=None; signer=''
        notes.append('The quoted original sender in this manual forward is user-supplied text.')
    gov_claim=bool(re.search(r'income\s*tax|incometax|cgst|sgst|gstn|cbic|epfo|provident fund|esic|fssai',original_name+' '+message.text[:500],re.I))
    return {'ingestion_mode':'MANUAL_FORWARD' if forwarded else 'AUTO_FORWARD_RULE',
        'forwarder_email':outer,'original_sender_name':original_name,'original_sender_email':email,
        'original_sender_domain':domain,'is_whitelisted_gov_domain':official(domain),
        'claims_gov_authority_in_display':gov_claim,'spoofing_detected':bool(gov_claim and domain and not official(domain)),
        'original_sender_verified':verified,'arc_validated':arc,'dkim_signing_domain':signer or None,
        'arc_dkim_passed':True if verified else None,'arc_spf_passed':spf,'dmarc_passed':None,
        'authentication_status':'verified-arc' if arc else 'verified-dkim' if verified else 'unverified',
        'forensic_notes':notes}
