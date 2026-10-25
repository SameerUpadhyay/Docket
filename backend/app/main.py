import json,re,uuid,hashlib
from datetime import date,datetime,timezone
from email import policy
from email.parser import Parser
from io import BytesIO
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI,UploadFile,File,Form,HTTPException,Response,Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from app.config import DATA_DIR,MAX_UPLOAD_BYTES
from app import config,auth
from app.security import security_boundary,BodyLimitMiddleware
from app.uploads import validate_upload
from app.models.schemas import *
from app.models import database
from app.engines.fraud_guard import run_forensic_authenticity_check
from app.engines.pii_scrubber import scrub_pii_before_llm
from app.engines.limitation_engine import compute_statutory_limitation
from app.engines.risk_scorer import calculate_deterministic_severity
from app.engines.triage_llm import triage_with_gemini
from app.engines.gmail_filter_gen import generate_gmail_filter_xml
from app.engines.exporter import make_zip,make_pdf,brief_text
from app.engines.document_reader import extract_document_details,VISION_BINARY
from app.workers.deadline_watchdog import preview_alerts

DEMO_TODAY=date(2026,10,24)

def seed():
    books={b['id']:b for b in json.loads((DATA_DIR/'statutory_playbooks.json').read_text())}
    for c in json.loads((DATA_DIR/'demo_cases.json').read_text()):
        if database.get(c['id']): continue
        f=run_forensic_authenticity_check(c['email'],'dkim=pass; spf=pass',c['raw_text'],trusted_auth=True)
        f.verification_note='Simulated fixture signals. DIN format is not live portal verification.'
        redacted,_,count=scrub_pii_before_llm(c['raw_text'])
        t=LLMTriageExtraction.model_validate(books[c['id']]['triage']) if c['id'] in books else None
        limitation=compute_statutory_limitation(c['issue'],c['service'],c['window'],DEMO_TODAY,allow_rollover=c.get('rollover',False)) if t else None
        tier,score=calculate_deterministic_severity(f,t,limitation) if t else (SeverityTier.PHISHING_SCAM,100)
        database.save(CompleteNoticeDossier(id=c['id'],ingested_at=c['service']+'T09:00:00+05:30',ingestion_channel='DEMO_FIXTURE',state=NoticeState.TRIAGED if t else NoticeState.PHISHING_QUARANTINED,severity=tier,deterministic_risk_score=score,forensics=f,limitation=limitation,triage=t,redacted_ocr_excerpt=redacted,pii_tokens_redacted_count=count,is_demo=True,analysis_mode='deterministic-demo',original_filename=c['id']+'.txt',review_notes=['Demo reference date: 24 October 2026. Figures and identities are fictional.']+(['Office-closure extension is a demonstration assumption; obtain professional confirmation.'] if c.get('rollover') else [])))

@asynccontextmanager
async def lifespan(app):
    config.validate_production()
    database.migrate()
    if config.DEMO_MODE: seed()
    yield

app=FastAPI(title='Docket · business notice workspace',lifespan=lifespan,docs_url=None if config.PRODUCTION else '/docs',redoc_url=None)
app.add_middleware(BodyLimitMiddleware)
app.middleware('http')(security_boundary)
app.add_middleware(CORSMiddleware,allow_origins=list(config.ALLOWED_ORIGINS),allow_credentials=True,allow_methods=['GET','POST','PATCH','DELETE','OPTIONS'],allow_headers=['Content-Type','Authorization','X-Workspace-ID','X-Docket-Request'])
app.include_router(auth.router)

@app.get('/api/health')
def health(): return {'status':'ok'}

@app.get('/api/notices',response_model=list[CompleteNoticeDossier])
def notices():
    items=database.all_notices()
    for d in items:
        if d.limitation and not d.is_demo:
            l=d.limitation
            d.limitation=compute_statutory_limitation(l.date_of_issue,l.date_of_service,l.statutory_window_days,allow_rollover=l.holiday_rollover_applied)
            d.severity,d.deterministic_risk_score=calculate_deterministic_severity(d.forensics,d.triage,d.limitation)
            if d.triage.notice_type_title.startswith('Unclassified') and d.severity==SeverityTier.GREEN:
                d.severity,d.deterministic_risk_score=SeverityTier.AMBER,max(32,d.deterministic_risk_score)
    return sorted(items,key=lambda d:(d.severity==SeverityTier.PHISHING_SCAM,d.limitation.effective_legal_deadline if d.limitation else '9999'))

def need_notice(notice_id):
    d=database.get(notice_id)
    if not d: raise HTTPException(404,'Notice not found.')
    if d.limitation and d.triage and not d.is_demo:
        l=d.limitation
        d.limitation=compute_statutory_limitation(l.date_of_issue,l.date_of_service,l.statutory_window_days,allow_rollover=l.holiday_rollover_applied)
        d.severity,d.deterministic_risk_score=calculate_deterministic_severity(d.forensics,d.triage,d.limitation)
        if d.triage.notice_type_title.startswith('Unclassified') and d.severity==SeverityTier.GREEN:
            d.severity,d.deterministic_risk_score=SeverityTier.AMBER,max(32,d.deterministic_risk_score)
    return d

def require_open(d):
    if not d.forensics.safe_to_process: raise HTTPException(409,'Quarantined notices cannot enter the reply workflow.')
    if d.state==NoticeState.SUBMITTED_CLOSED: raise HTTPException(409,'Closed notices are read-only.')

async def read_upload(file):
    content=await file.read(MAX_UPLOAD_BYTES+1)
    if len(content)>MAX_UPLOAD_BYTES: raise HTTPException(413,'File exceeds the 10 MB limit.')
    if not content: raise HTTPException(422,'The uploaded file is empty.')
    return content

@app.post('/api/notices/analyze',response_model=CompleteNoticeDossier)
async def analyze(file:UploadFile=File(...),date_of_issue:str=Form(...),date_of_service:str=Form(...),window_days:int=Form(...),raw_headers:str=Form(''),channel:str=Form('PDF_UPLOAD'),confirm_office_rollover:bool=Form(False),ocr_language:str=Form('auto')):
    if channel not in ('PDF_UPLOAD','EMAIL_WEBHOOK','WHATSAPP_SNAP'): raise HTTPException(422,'Invalid channel.')
    try: limitation=compute_statutory_limitation(date_of_issue,date_of_service,window_days,allow_rollover=confirm_office_rollover)
    except ValueError as exc: raise HTTPException(422,str(exc))
    content=await read_upload(file)
    await run_in_threadpool(validate_upload,content,file.filename or 'notice.txt')
    extraction=await run_in_threadpool(extract_document_details,content,file.filename or 'notice.txt',ocr_language,bool(database.preferences()['cloud_ocr']))
    text,qr_payloads,reader_notes=extraction.text,extraction.qr,extraction.notes
    headers=Parser(policy=policy.default).parsestr(raw_headers[:20000])
    attachment_names=[file.filename or '']
    if (file.filename or '').lower().endswith('.eml'):
        mail=Parser(policy=policy.default).parsestr(text)
        headers=mail
        attachment_names.extend(part.get_filename() or '' for part in mail.iter_attachments())
        body=mail.get_body(preferencelist=('plain',))
        text=body.get_content() if body else ''
        if not text.strip(): raise HTTPException(422,'EML requires a plain-text message body.')
        if list(mail.iter_attachments()):
            reader_notes.append('EML attachment names were screened; attachment contents were not analyzed. Upload each notice attachment separately.')
    if len(text)>200000: raise HTTPException(413,'Extracted text exceeds 200,000 characters.')
    urls=re.findall(r'(?:https?://|upi://)[^\s<>"\']+',text)
    f=run_forensic_authenticity_check(str(headers.get('From','')),str(headers.get('Authentication-Results','')),text,urls,qr_payloads,attachment_names)
    text_for_storage=text+('\n\nDECODED QR PAYLOADS\n'+'\n'.join(qr_payloads) if qr_payloads else '')
    redacted,redaction_map,count=scrub_pii_before_llm(text_for_storage)
    from app.ocr.bilingual_ocr_engine import analyze_extraction,redact_analysis
    ocr_analysis=redact_analysis(analyze_extraction(extraction,Path(file.filename or 'notice.txt').name),redaction_map)
    observed=ocr_analysis.structured_triage
    if observed.date_of_issue_iso and observed.date_of_issue_iso!=date_of_issue:
        ocr_analysis.warnings.append('Entered issue date differs from the OCR candidate. Confirm the original before relying on the planning date.')
    if observed.response_window_days and observed.response_window_days!=window_days:
        ocr_analysis.warnings.append('Entered response period differs from the OCR candidate. Confirm which period applies.')
    triage=None
    tier=SeverityTier.PHISHING_SCAM
    score=100
    mode='quarantine / no external AI'
    notes=['Dates and response window were supplied by the uploader; verify against the original notice.','A zero extracted amount means unknown or no labelled demand; verify the original.','DKIM/SPF and portal DIN authentication have not been independently verified.',*reader_notes]
    if f.safe_to_process:
        triage,mode=await run_in_threadpool(triage_with_gemini,redacted,date_of_issue,window_days, bool(database.preferences()['external_ai']))
        evidence=ocr_analysis.structured_triage
        if mode.startswith('gemini-summary'):
            evidence.core_allegation_english=triage.plain_english_summary
            evidence.core_allegation_hindi=triage.vernacular_summary_hindi
        else:
            triage.plain_english_summary=evidence.core_allegation_english
            triage.vernacular_summary_hindi=evidence.core_allegation_hindi
        if evidence.total_demand_inr is not None: triage.financial_demand_inr=float(evidence.total_demand_inr)
        if evidence.notice_domain.value!='UNCLASSIFIED' and triage.notice_type_title.startswith('Unclassified'): triage.notice_type_title='Unclassified · '+evidence.specific_form_code+' · professional review'
        if evidence.statutory_sections_invoked: triage.statutory_act_and_section+=' · '+', '.join(evidence.statutory_sections_invoked)
        triage.has_criminal_or_arrest_clause|=evidence.threatens_criminal_prosecution
        triage.has_bank_freeze_or_eway_block_threat|=evidence.threatens_bank_attachment_or_eway_block
        tier,score=calculate_deterministic_severity(f,triage,limitation)
        if triage.notice_type_title.startswith('Unclassified') and tier==SeverityTier.GREEN:
            tier,score=SeverityTier.AMBER,max(score,32)
    dossier=CompleteNoticeDossier(id=uuid.uuid4().hex[:12],ingested_at=datetime.now(timezone.utc).isoformat(),ingestion_channel=channel,state=NoticeState.TRIAGED if f.safe_to_process else NoticeState.PHISHING_QUARANTINED,severity=tier,deterministic_risk_score=score,forensics=f,limitation=limitation if triage else None,triage=triage,redacted_ocr_excerpt=redacted,pii_tokens_redacted_count=count,analysis_mode=mode,original_filename=Path(file.filename or 'notice.txt').name,review_notes=notes,source_sha256=hashlib.sha256(content).hexdigest(),ocr_report=extraction.quality,ocr_analysis=ocr_analysis)
    saved=database.save(dossier,'case.created')
    if database.preferences()['retain_original']:
        await run_in_threadpool(database.save_evidence,saved.id,'original',saved.original_filename,content)
    return saved

@app.patch('/api/notices/{notice_id}/checklist/{doc_id}',response_model=CompleteNoticeDossier)
def checklist(notice_id:str,doc_id:str,update:ChecklistUpdate):
    d=need_notice(notice_id); require_open(d)
    item=next((x for x in d.triage.required_documents if x.doc_id==doc_id),None)
    if not item: raise HTTPException(404,'Checklist item not found.')
    item.is_collected=update.is_collected
    if d.state!=NoticeState.CA_ESCALATED:
        count=sum(x.is_collected for x in d.triage.required_documents)
        d.state=NoticeState.DRAFT_READY if count==len(d.triage.required_documents) else NoticeState.DOCS_GATHERING if count else NoticeState.TRIAGED
    return database.save(d)

@app.post('/api/notices/{notice_id}/evidence/{doc_id}',response_model=CompleteNoticeDossier)
async def evidence_upload(notice_id:str,doc_id:str,file:UploadFile=File(...)):
    d=need_notice(notice_id); require_open(d)
    item=next((x for x in d.triage.required_documents if x.doc_id==doc_id),None)
    if not item: raise HTTPException(404,'Checklist item not found.')
    content=await read_upload(file)
    name=Path(file.filename or 'evidence').name
    if Path(name).suffix.lower() not in ('.pdf','.txt','.png','.jpg','.jpeg','.csv','.xlsx'): raise HTTPException(415,'Unsupported evidence format.')
    await run_in_threadpool(validate_upload,content,name)
    await run_in_threadpool(database.save_evidence,notice_id,doc_id,name,content)
    item.attachment_name=name
    item.is_collected=True
    if d.state!=NoticeState.CA_ESCALATED:
        d.state=NoticeState.DRAFT_READY if all(x.is_collected for x in d.triage.required_documents) else NoticeState.DOCS_GATHERING
    return database.save(d)

@app.patch('/api/notices/{notice_id}/draft',response_model=CompleteNoticeDossier)
def draft(notice_id:str,update:DraftUpdate):
    d=need_notice(notice_id); require_open(d)
    if not d.is_demo and update.expected_revision!=d.revision:
        raise HTTPException(409,"This case changed. Refresh it before saving your draft; copy your edits first.")
    d.draft_reply=update.draft_reply
    return database.save(d)

@app.patch('/api/notices/{notice_id}/state',response_model=CompleteNoticeDossier)
def state(notice_id:str,update:StateUpdate):
    d=need_notice(notice_id); require_open(d)
    if update.state=='SUBMITTED_CLOSED' and not d.is_demo and not d.submission_receipt:
        raise HTTPException(409,'Record a submission acknowledgement before closing this case.')
    d.state=NoticeState(update.state)
    return database.save(d)

@app.get('/api/privacy/gmail-filter.xml')
def gmail(webhook_email:str):
    try: xml=generate_gmail_filter_xml(webhook_email)
    except ValueError as exc: raise HTTPException(422,str(exc))
    return Response(xml,media_type='application/xml',headers={'Content-Disposition':'attachment; filename="docket-gov-notice-filter.xml"'})

@app.post('/api/notices/{notice_id}/export-ca-brief')
def export(notice_id:str):
    return Response(make_zip(need_notice(notice_id)),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="docket-{notice_id}.zip"'})

@app.get('/api/notices/{notice_id}/reply.pdf')
def reply_pdf(notice_id:str):
    d=need_notice(notice_id)
    if not d.triage: raise HTTPException(409,'Quarantined notices have no reply draft.')
    return Response(make_pdf(d.draft_reply or d.triage.draft_reply_template),media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="draft-for-review.pdf"'})

@app.get('/api/notices/{notice_id}/report.pdf')
def report(notice_id:str):
    return Response(make_pdf(brief_text(need_notice(notice_id))),media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="docket-report.pdf"'})

@app.get('/api/watchdog')
def watchdog():
    with database.connect() as tx:
        rows=tx.execute('SELECT notice_id,due,status,attempts FROM reminder_jobs WHERE workspace=? ORDER BY due',(database.scope.get(),)).fetchall()
    return {'mode':'PERSISTENT_EMAIL_QUEUE','delivery_configured':config.email_configured(),'jobs':[dict(r) for r in rows]}

from app.workspace import router as workspace_router
app.include_router(workspace_router)

from app.ocr.pipeline_router import router as ocr_router
app.include_router(ocr_router)
