"""Durable local-only intake; external summaries require separate owner consent."""
import hashlib,json,re,time,uuid
from datetime import datetime,timezone
from pathlib import Path
from fastapi import HTTPException
from app import config
from app.models import database as db
from app.models.schemas import CompleteNoticeDossier,NoticeState,SeverityTier,AuthenticityVerdict
from app.engines.document_reader import extract_document_details,Extraction
from app.engines.fraud_guard import run_forensic_authenticity_check
from app.engines.pii_scrubber import scrub_pii_before_llm
from app.engines.triage_llm import triage_with_gemini
from app.engines.risk_scorer import calculate_deterministic_severity
from app.ocr.bilingual_ocr_engine import analyze_extraction,redact_analysis
from app.uploads import validate_upload
from . import store
from .schemas_email import InboundEmail,normalize
from .arc_header_forensics import unwrap_forwarded_email_forensics

CONFIRM_CODE=re.compile(r'(?:confirmation\s*code|पुष्टि\s*कोड)\s*[:\-]?\s*(\d{8,10})(?!\d)',re.I)
CONFIRM_LINK=re.compile(r'https://(?:mail-settings\.google\.com|mail\.google\.com)/mail/vf-[a-zA-Z0-9_?=&%./+-]+')

def _verification(message,chain,address,simulation):
    if chain['original_sender_email']!='forwarding-noreply@google.com': return None
    if not simulation and (not chain['original_sender_verified'] or address.lower() not in message.text.lower()): return None
    code=CONFIRM_CODE.search(message.text); link=CONFIRM_LINK.search(message.text)
    if not code and not link: return None
    return {'confirmation_code':code.group(1) if code else None,'confirmation_url':link.group(0) if link and not simulation else None,
        'received_at':datetime.now(timezone.utc).isoformat(),'auto_verified':False,'simulation':simulation}

def _redact_tree(value,mapping):
    if isinstance(value,str):
        for token,secret in sorted(mapping.items(),key=lambda item:len(item[1]),reverse=True): value=value.replace(secret,token)
        return value
    if isinstance(value,list): return [_redact_tree(item,mapping) for item in value]
    if isinstance(value,dict): return {key:_redact_tree(item,mapping) for key,item in value.items()}
    return value

def _build(message,simulation,chain,*,allow_external_summary=True):
    text=message.subject+'\n'+message.text
    names=[name for name,_ in message.attachments]
    blocked=[]
    # Screen every attachment before any OCR or optional model call.
    for name,content in message.attachments:
        try:
            if Path(name).suffix.lower()=='.eml': raise HTTPException(415,'Attached email is not accepted.')
            if not content: raise HTTPException(422,'Empty attachment.')
            validate_upload(content,name)
        except HTTPException as error:
            if error.status_code>=500: raise
            blocked.append(name)
    guard=lambda value,qr: run_forensic_authenticity_check(
        f"{chain['original_sender_name']} <{chain['original_sender_email']}>",document_text=value,
        extracted_urls=re.findall(r'(?:https?://|upi://)[^\s<>"\']+',value),qr_decoded_payloads=qr,attachment_names=names)
    fraud=guard(text,[]); qr=[]; primary=None; attachment_reports=[]; total_pages=0
    if fraud.safe_to_process and not blocked:
        for name,content in message.attachments:
            # Email attachments are always read locally. Sharing original images
            # requires the distinct, explicit upload flow and its cloud consent.
            extraction=extract_document_details(content,name,'auto',False)
            analysis=analyze_extraction(extraction,name)
            total_pages+=analysis.page_count
            if total_pages>12: raise HTTPException(422,'Email attachments exceed the combined 12-page processing limit.')
            if primary is None: primary=analysis
            qr.extend(extraction.qr)
            text+='\n\nATTACHMENT: '+name+'\n'+extraction.text
            attachment_reports.append({'name':name,'pages':analysis.page_count,'engine':analysis.extraction_engine_used})
        if len(text)>200000: raise HTTPException(422,'Combined email extraction exceeds 200,000 characters.')
        fraud=guard(text,qr)
    if blocked:
        fraud.safe_to_process=False; fraud.verdict=AuthenticityVerdict.PHISHING_SCAM; fraud.fraud_risk_score=100
        fraud.scam_flags.append('Unsafe or unsupported attachments were isolated; their contents were not processed.')
    if chain['original_sender_verified']:
        fraud.dkim_passed=True; fraud.spf_passed=chain['arc_spf_passed']
        if chain['is_whitelisted_gov_domain'] and fraud.fraud_risk_score==0: fraud.verdict=AuthenticityVerdict.VERIFIED_GOV
    fraud.verification_note=' '.join(chain['forensic_notes'])+' Mail provenance does not authenticate the notice or its legal claims.'
    text+='\n'+ '\n'.join(qr)
    redacted,mapping,count=scrub_pii_before_llm(text)
    if primary is None: primary=analyze_extraction(Extraction(text,qr,[],{'pages':[]}), 'email.txt')
    primary=redact_analysis(primary,mapping)
    triage=None; mode='email quarantine / no external AI'; tier=SeverityTier.PHISHING_SCAM; score=100
    if fraud.safe_to_process:
        observed=primary.structured_triage
        triage,mode=triage_with_gemini(redacted,observed.date_of_issue_iso,observed.response_window_days,
            bool(db.preferences()['external_ai']) and not simulation and allow_external_summary)
        if not mode.startswith('gemini-summary'):
            triage.plain_english_summary=observed.core_allegation_english
            triage.vernacular_summary_hindi=observed.core_allegation_hindi
        if observed.total_demand_inr is not None: triage.financial_demand_inr=float(observed.total_demand_inr)
        if observed.specific_form_code and observed.notice_domain.value!='UNCLASSIFIED': triage.notice_type_title=observed.specific_form_code
        if observed.statutory_sections_invoked: triage.statutory_act_and_section=', '.join(observed.statutory_sections_invoked)
        triage.core_allegation_or_query=observed.core_allegation_english
        triage.has_criminal_or_arrest_clause|=observed.threatens_criminal_prosecution
        triage.has_bank_freeze_or_eway_block_threat|=observed.threatens_bank_attachment_or_eway_block
        tier,score=calculate_deterministic_severity(fraud,triage,None)
        if tier==SeverityTier.GREEN: tier,score=SeverityTier.AMBER,max(score,32)
        # Optional summaries may echo prompt text; scrub the complete result again.
        triage=type(triage).model_validate(_redact_tree(triage.model_dump(),mapping))
    identifier=uuid.uuid4().hex[:12]
    dossier=CompleteNoticeDossier(id=identifier,ingested_at=datetime.now(timezone.utc).isoformat(),ingestion_channel='EMAIL_FORWARD',
        state=NoticeState.TRIAGED if fraud.safe_to_process else NoticeState.PHISHING_QUARANTINED,severity=tier,
        deterministic_risk_score=score,forensics=fraud,triage=triage,limitation=None,facts_confirmed=False,
        redacted_ocr_excerpt=redacted,pii_tokens_redacted_count=count,is_demo=simulation,analysis_mode=mode,
        original_filename=message.attachments[0][0] if message.attachments and not blocked else 'forwarded-email.eml',
        source_sha256=hashlib.sha256(message.raw or text.encode()).hexdigest(),ocr_analysis=primary,
        email_intake={'subject':_redact_tree(message.subject,mapping),'chain_forensics':chain,
            'attachments':attachment_reports,'blocked_attachments':len(blocked),'simulation':simulation,'pii_vault_expires_at':time.time()+86400},
        review_notes=['Received by selective email forwarding. No mailbox access was requested.',
            'Confirm the issue date, proof of service and applicable response period before planning a deadline.',
            'All attachments were screened; accepted images were processed locally. Identifier masking may miss personal data.',
            *(['Development simulation: fictional mail, not a verified delivery.'] if simulation else [])])
    return dossier,mapping,blocked

def process_receipt(identifier):
    now=time.time()
    with db.connect() as tx:
        row=tx.execute("UPDATE email_receipts SET status='processing',lease_until=?,attempts=attempts+1 WHERE id=? AND created_at>? AND ((status IN ('pending','retry') AND lease_until<=?) OR (status='processing' AND lease_until<?)) RETURNING *",
            (now+900,identifier,now-86400,now,now)).fetchone()
        if not row: return
        row=dict(row)
        route=tx.execute('SELECT address FROM email_routes WHERE id=? AND workspace=? AND enabled=1',(row['route_id'],row['workspace'])).fetchone()
        if not route:
            tx.execute("UPDATE email_receipts SET status='cancelled',payload='' WHERE id=?",(identifier,)); return
    contexts=[(db.scope,db.scope.set(row['workspace'])),(db.actor,db.actor.set('email-ingestion')),(db.role,db.role.set('owner'))]
    try:
        payload=InboundEmail.model_validate_json(db.unseal(row['payload']))
        message=normalize(payload)
        chain=unwrap_forwarded_email_forensics(message)
        verification=_verification(message,chain,db.unseal(route['address']).decode(),bool(row['simulation']))
        result=None if verification else _build(message,bool(row['simulation']),chain)
        with db.connect() as tx:
            # Lock/recheck consent after potentially long OCR and signature checks.
            enabled=tx.execute('UPDATE email_routes SET enabled=enabled WHERE id=? AND workspace=? AND enabled=1 RETURNING id',(row['route_id'],row['workspace'])).fetchone()
            active=tx.execute("SELECT id FROM email_receipts WHERE id=? AND status='processing' AND lease_until=?",(identifier,row['lease_until'])).fetchone()
            if not enabled or not active:
                tx.execute("UPDATE email_receipts SET status='cancelled',payload='' WHERE id=? AND status='processing' AND lease_until=?",(identifier,row['lease_until'])); return
            if verification:
                tx.execute('INSERT INTO email_verifications VALUES (?,?,?,?) ON CONFLICT(workspace) DO UPDATE SET route_id=excluded.route_id,payload=excluded.payload,expires=excluded.expires',
                    (row['workspace'],row['route_id'],db.seal(json.dumps(verification)),time.time()+600))
                store.publish(tx,'GMAIL_VERIFICATION_RECEIVED',{'simulation':bool(row['simulation'])},ttl=600)
                tx.execute("UPDATE email_receipts SET status='verification',payload='',lease_until=0 WHERE id=?",(identifier,))
            else:
                dossier,mapping,blocked=result; dossier.revision=1
                tx.execute('INSERT INTO cases_v2 VALUES (?,?,?,?)',(row['workspace'],dossier.id,db.seal(dossier.model_dump_json()),time.time()))
                db.event(dossier.id,'email.ingested',{'receipt_id':identifier,'simulation':bool(row['simulation'])},tx)
                tx.execute('INSERT INTO email_pii_vault VALUES (?,?,?,?,?)',(uuid.uuid4().hex,row['workspace'],dossier.id,db.seal(json.dumps(mapping)),dossier.email_intake['pii_vault_expires_at']))
                preferences=tx.execute('SELECT retain_original FROM preferences WHERE workspace=?',(row['workspace'],)).fetchone()
                if preferences and preferences['retain_original'] and not blocked and not row['simulation']:
                    evidence=message.attachments or [('forwarded-email.eml',message.raw or (message.subject+'\n'+message.text).encode())]
                    for index,(name,content) in enumerate(evidence):
                        tx.execute('INSERT INTO files_v2 VALUES (?,?,?,?,?)',(row['workspace'],dossier.id,'original' if index==0 else 'email-'+str(index+1),name,db.seal(content)))
                store.publish(tx,'NEW_NOTICE_INGESTED',{'notice_id':dossier.id,'quarantined':not dossier.forensics.safe_to_process,'simulation':bool(row['simulation'])})
                tx.execute("UPDATE email_receipts SET status='processed',notice_id=?,payload='',lease_until=0 WHERE id=?",(dossier.id,identifier))
    except Exception as error:
        transient=isinstance(error,HTTPException) and error.status_code>=500
        code='screening-unavailable' if transient else 'message-rejected' if isinstance(error,HTTPException) else 'processing-failed'
        retry=(transient or not isinstance(error,HTTPException)) and row['attempts']<8
        with db.connect() as tx:
            updated=tx.execute("UPDATE email_receipts SET status=?,error_code=?,lease_until=?,payload=CASE WHEN ?=1 THEN payload ELSE '' END WHERE id=? AND status='processing' AND lease_until=? RETURNING id",
                ('retry' if retry else 'rejected',code,time.time()+min(3600,30*2**row['attempts']) if retry else 0,int(retry),identifier,row['lease_until'])).fetchone()
            if updated: store.publish(tx,'EMAIL_PROCESSING_DELAYED' if retry else 'EMAIL_REJECTED',{'receipt_id':identifier,'reason':code})
    finally:
        for variable,token in reversed(contexts): variable.reset(token)

def process_next():
    with db.connect() as tx:
        store.cleanup(tx)
        row=tx.execute("SELECT id FROM email_receipts WHERE created_at>? AND status IN ('pending','retry','processing') AND lease_until<=? ORDER BY created_at LIMIT 1",(time.time()-86400,time.time())).fetchone()
    if not row: return False
    process_receipt(row['id']); return True
