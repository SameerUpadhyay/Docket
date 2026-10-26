"""Business access, consent, case review, submission records and data rights."""
import hashlib,json,time,secrets,uuid
from datetime import date,datetime,time as day_time,timedelta
from zoneinfo import ZoneInfo
from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED
from fastapi import APIRouter,HTTPException,Request,Response,UploadFile,File
from fastapi.responses import HTMLResponse
from pydantic import BaseModel,Field
from typing import Literal
from app import auth,config,mail
from app.models import database as db
from app.engines.limitation_engine import compute_statutory_limitation
from app.engines.risk_scorer import calculate_deterministic_severity
router=APIRouter(prefix='/api')

def notice_or_404(notice_id):
    d=db.get(notice_id)
    if not d: raise HTTPException(404,'Notice not found.')
    return d

def open_case(d):
    if d.is_demo or not d.triage or d.state.value=='SUBMITTED_CLOSED': raise HTTPException(409,'This action requires an open real case.')

class Invite(auth.EmailOnly):
    role:Literal['reviewer','editor']='reviewer'
class Accept(BaseModel):
    token:str=Field(min_length=20,max_length=200)
class Preferences(BaseModel):
    email_reminders:bool=False
    external_ai:bool=False
    cloud_ocr:bool=False
    retain_original:bool=False
class Facts(BaseModel):
    issue:str
    service:str
    window:int=Field(ge=1,le=365)
    amount:float=Field(ge=0,le=1e15,allow_inf_nan=False)
    authority:str=Field(min_length=1,max_length=300)
    section:str=Field(min_length=1,max_length=300)
    basis:str=Field(min_length=10,max_length=3000)
    office_rollover:bool=False
class Review(BaseModel):
    decision:Literal['COMMENT','CHANGES_REQUESTED','REVIEWED']='COMMENT'
    comment:str=Field(min_length=5,max_length=5000)
class Submission(BaseModel):
    acknowledgement:str=Field(min_length=3,max_length=300)
    submitted_at:date
    channel:str=Field(min_length=3,max_length=300)

@router.get('/public/config')
def public_config():
    return {'environment':config.ENVIRONMENT,'email_delivery':config.MAIL_TRANSPORT if config.email_configured() else 'development-outbox','support_email':config.SUPPORT_EMAIL,'policy_version':config.POLICY_VERSION,'authentication_required':True}

@router.get('/ready')
def ready():
    with db.connect() as tx:
        tx.execute('SELECT version FROM schema_migrations').fetchall()
    return {'status':'ready','database':'postgresql' if config.DATABASE_URL else 'sqlite','mode':config.ENVIRONMENT}

@router.get('/public/privacy',response_class=HTMLResponse)
def privacy():
    # This operational draft must be customized with the actual legal entity before release.
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Docket privacy</title><body style="font:17px/1.7 system-ui;max-width:760px;margin:40px auto;padding:24px;color:#1b365d"><h1>Docket privacy notice</h1><p>Version 2026-10-25 · pilot policy draft. The operator's legal name, support contact, processors and backup retention must be published before public release.</p><p>We process your email, profile, business name, notice text, evidence, case actions and account security records to provide your notice workspace. Business owners control access given to employees and advisors. Documents may contain sensitive personal and financial information.</p><p>Case content, files and case history are encrypted at rest by the application. Account and scheduling metadata also require encrypted infrastructure volumes and restricted database access. HTTPS protects production connections. Regex masking does not guarantee anonymization.</p><p>Cloud OCR, external AI summaries, retained original documents and email deadline reminders are off until the business owner enables them. Enabling cloud OCR allows original document images to be sent to the configured Gemini or AWS Textract provider. Gemini supports English/Hindi extraction; Textract is used for English only. Local OCR is used when cloud processing is disabled. It is separate from optional AI summaries, which send masked text to the configured Google Gemini service; review the provider's terms and your authority to share the material. Email codes use the configured email provider. Mobile OCR runs on the device.</p><p>Selective email forwarding is optional and configured by the business owner. Docket never requests inbox access. Forwarded messages and attachments pass through the configured receiving provider; keyword filters may include personal messages, so review the rule before enabling it. Email attachments use local OCR. Incoming cases have no planned deadline until facts are confirmed. Forwarding codes expire after ten minutes; encrypted reversible identifier maps and queued raw content after 24 hours; delivery metadata after 30 days. Owners/editors can explicitly reveal temporary identifiers, and owner exports include unexpired maps. Disabling or replacing a receiving address cancels queued work; remove the rule in Gmail too. Provider-side retention and infrastructure backups are governed by the operator and provider policies.</p><p>Records remain until you delete a case or account. Account deletion removes owned business workspaces and revokes all sessions. Other businesses' records are controlled by their owners. Backup copies expire under the operator's published retention policy; deletion must be replayed if an older backup is restored.</p><p>To export or delete your account, sign in at the web app, open Account and choose Export data or Delete account. Password recovery is available on the sign-in screen. This route works without installing the Android app. Contact the operator for access, correction, withdrawal or complaints.</p><p>No notice is automatically authenticated or legally filed. Your advisor and you remain responsible for factual, statutory and submission checks.</p><a href="/">Open Docket to manage your account</a></body></html>'''

@router.get('/public/terms',response_class=HTMLResponse)
def terms():
    return '<!doctype html><html lang="en"><meta charset="utf-8"><title>Docket terms</title><body style="font:17px/1.7 system-ui;max-width:760px;margin:40px auto;padding:24px"><h1>Pilot terms</h1><p>Docket provides planning and document organization support. Dates, risk scores, summaries and templates require human review. The service does not provide automatic legal representation, portal authentication, filing or guaranteed reminders. Use independently verified official channels for payments and submissions.</p><p>You must have authority to upload and share documents. Business owners manage and revoke advisor access. Reviewers are invited by the owner; Docket does not certify their qualifications. Keep credentials private and report suspected compromise to the operator.</p><p>These pilot terms require review and completion with operator identity, support, pricing, applicable jurisdiction and dispute terms before public launch.</p><a href="/api/public/privacy">Privacy notice</a></body></html>'

@router.get('/workspace/preferences')
def preferences(): return db.preferences()

@router.patch('/workspace/preferences')
def update_preferences(body:Preferences):
    auth.owner()
    if body.email_reminders and not config.email_configured() and config.PRODUCTION: raise HTTPException(503,'Email reminders are not configured.')
    with db.connect() as tx:
        tx.execute('INSERT INTO preferences VALUES (?,?,?,?) ON CONFLICT(workspace) DO UPDATE SET email_reminders=excluded.email_reminders,external_ai=excluded.external_ai,retain_original=excluded.retain_original',(db.scope.get(),int(body.email_reminders),int(body.external_ai),int(body.retain_original)))
        tx.execute('INSERT INTO ocr_preferences VALUES (?,?) ON CONFLICT(workspace) DO UPDATE SET cloud_ocr=excluded.cloud_ocr',(db.scope.get(),int(body.cloud_ocr)))
        db.event('','consent.changed',body.model_dump(),tx)
        if not body.email_reminders: tx.execute("UPDATE reminder_jobs SET status='cancelled' WHERE workspace=? AND status<>'sent'",(db.scope.get(),))
    if body.email_reminders:
        for d in db.all_notices(): schedule(d)
    return db.preferences()

@router.get('/workspace/members')
def members():
    auth.owner()
    with db.connect() as tx:
        rows=tx.execute('SELECT users.id,users.name,users.email,members.role FROM members JOIN users ON users.id=members.user_id WHERE members.workspace=?',(db.scope.get(),)).fetchall()
    return [dict(r) for r in rows]

@router.post('/workspace/invitations')
def invite(body:Invite):
    auth.owner(); email=auth.Credentials.email_valid(body.email)
    auth.throttle('invite:'+db.scope.get(),10,3600)
    token=secrets.token_urlsafe(32)
    with db.connect() as tx:
        tx.execute('DELETE FROM invitations WHERE workspace=? AND email=?',(db.scope.get(),email))
        tx.execute('INSERT INTO invitations VALUES (?,?,?,?,?)',(auth.digest(token),db.scope.get(),email,body.role,time.time()+48*3600))
        db.event('','member.invited',{'email':email,'role':body.role},tx)
    mail.send_email(email,'Docket · business workspace invitation',f'You have been invited with {body.role} access. Create and verify an account using this email, sign in, then enter this invitation code in Account → Join workspace:\n\n{token}\n\nExpires in 48 hours. Only accept if you recognize the business owner.\n{config.PUBLIC_URL}')
    return {'message':'Invitation sent. It expires in 48 hours.'}

@router.post('/workspace/invitations/accept')
def accept(body:Accept,request:Request):
    user=auth.current(request)
    with db.connect() as tx:
        row=tx.execute('DELETE FROM invitations WHERE hash=? AND email=? AND expires>? RETURNING workspace,role',(auth.digest(body.token),user['email'],time.time())).fetchone()
        if not row: raise HTTPException(400,'Invitation is invalid, expired or belongs to another email.')
        tx.execute('INSERT INTO members VALUES (?,?,?) ON CONFLICT(workspace,user_id) DO NOTHING',(row['workspace'],user['id'],row['role']))
    return {'message':'Workspace joined. Refresh your account and select the business.','workspace_id':row['workspace']}

@router.delete('/workspace/members/{user_id}')
def revoke(user_id:str):
    auth.owner()
    with db.connect() as tx:
        tx.execute("DELETE FROM members WHERE workspace=? AND user_id=? AND role<>'owner'",(db.scope.get(),user_id))
        db.event('','member.revoked',{'user_id':user_id},tx)
    return {'message':'Workspace access revoked.'}

@router.get('/notices/{notice_id}/history')
def history(notice_id:str):
    notice_or_404(notice_id)
    return db.history(notice_id)

@router.patch('/notices/{notice_id}/facts')
def confirm_facts(notice_id:str,body:Facts):
    d=notice_or_404(notice_id); open_case(d)
    try: d.limitation=compute_statutory_limitation(body.issue,body.service,body.window,allow_rollover=body.office_rollover)
    except ValueError as exc: raise HTTPException(422,str(exc))
    d.triage.date_of_issue_iso=body.issue
    d.triage.response_window_days=body.window
    d.triage.financial_demand_inr=body.amount
    d.triage.issuing_authority=body.authority
    d.triage.statutory_act_and_section=body.section
    d.facts_confirmed=True
    d.professional_review='PENDING'
    d.severity,d.deterministic_risk_score=calculate_deterministic_severity(d.forensics,d.triage,d.limitation)
    if d.triage.notice_type_title.startswith('Unclassified') and d.severity.value=='GREEN':
        from app.models.schemas import SeverityTier
        d.severity=SeverityTier.AMBER; d.deterministic_risk_score=max(32,d.deterministic_risk_score)
    db.event(d.id,'facts.confirmed',body.model_dump())
    saved=db.save(d); schedule(saved)
    return saved

@router.post('/notices/{notice_id}/reviews')
def review(notice_id:str,body:Review):
    d=notice_or_404(notice_id); open_case(d)
    if db.role.get() not in ('owner','reviewer'): raise HTTPException(403,'Professional review requires the owner or an invited reviewer.')
    if body.decision=='REVIEWED' and not d.facts_confirmed: raise HTTPException(409,'Confirm the extracted facts before recording a review.')
    db.event(d.id,'professional.'+body.decision.lower(),{'comment':body.comment})
    if body.decision!='COMMENT': d.professional_review=body.decision
    return db.save(d,'review.recorded')

@router.post('/notices/{notice_id}/submission')
def submission(notice_id:str,body:Submission):
    auth.writable(); d=notice_or_404(notice_id); open_case(d)
    if not d.submission_proof_name: raise HTTPException(409,'Attach the official submission receipt before recording its reference.')
    if not d.facts_confirmed or d.professional_review!='REVIEWED': raise HTTPException(409,'Confirm facts and record professional review before recording submission.')
    if body.submitted_at>datetime.now(ZoneInfo('Asia/Kolkata')).date(): raise HTTPException(422,'Submission date cannot be in the future.')
    if d.limitation and body.submitted_at<date.fromisoformat(d.limitation.date_of_service): raise HTTPException(422,'Submission date cannot precede the confirmed service date.')
    d.submission_receipt=body.acknowledgement; d.submitted_at=body.submitted_at.isoformat()
    db.event(d.id,'submission.recorded',body.model_dump(mode='json'))
    return db.save(d,'submission.recorded')

@router.delete('/notices/{notice_id}')
def delete_notice(notice_id:str):
    auth.owner(); notice_or_404(notice_id); db.delete_case(notice_id)
    return {'message':'Case, evidence, case history and queued reminders deleted.'}

@router.get('/account/export')
def export_account(request:Request):
    user=auth.current(request); auth.owner()
    output=BytesIO()
    with ZipFile(output,'w',ZIP_DEFLATED) as archive:
        archive.writestr('profile.json',json.dumps({'user':user,'workspace':db.scope.get(),'preferences':db.preferences()},indent=2))
        with db.connect() as tx:
            email_receipts=[dict(r) for r in tx.execute('SELECT id,status,notice_id,created_at,error_code,simulation FROM email_receipts WHERE workspace=?',(db.scope.get(),)).fetchall()]
            vaults=tx.execute('SELECT notice_id,payload FROM email_pii_vault WHERE workspace=? AND expires>?',(db.scope.get(),time.time())).fetchall()
        archive.writestr('email/receipts.json',json.dumps(email_receipts,indent=2))
        for vault in vaults: archive.writestr('email/identifiers/'+vault['notice_id']+'.json',db.unseal(vault['payload']))
        for d in db.all_notices():
            archive.writestr(f'cases/{d.id}/dossier.json',d.model_dump_json(indent=2))
            archive.writestr(f'cases/{d.id}/history.json',json.dumps(db.history(d.id),indent=2))
            manifest=[]
            for index,(doc_id,name,content) in enumerate(db.evidence(d.id)):
                extension=name.rsplit('.',1)[-1].lower() if '.' in name else 'bin'
                extension=extension if extension in ('pdf','txt','png','jpg','jpeg','csv','xlsx','eml') else 'bin'
                path=f'cases/{d.id}/files/{index+1}.{extension}'
                archive.writestr(path,content)
                manifest.append({'document_id':doc_id,'name':name,'path':path,'sha256':hashlib.sha256(content).hexdigest()})
            archive.writestr(f'cases/{d.id}/files/index.json',json.dumps(manifest,indent=2))
    return Response(output.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="docket-account-export.zip"'})

@router.get('/playbooks')
def playbooks():
    return {'version':'2026-10-25-unreviewed','review_status':'PROFESSIONAL_SIGN_OFF_REQUIRED','notice_families':['GST ASMT-10','Income Tax 143(1)','NI Act 138','EPFO 14B / 7Q'],'deadline_policy':'Uploader-confirmed dates and response window; jurisdiction-specific statutory applicability requires professional review.','sources':[{'title':'GST legislation and rules','url':'https://cbic-gst.gov.in/gst-acts.html'},{'title':'Income Tax Department','url':'https://www.incometax.gov.in/'},{'title':'India Code','url':'https://www.indiacode.nic.in/'},{'title':'EPFO','url':'https://www.epfindia.gov.in/'}]}

def schedule(d):
    if d.is_demo or not d.facts_confirmed or not d.limitation or d.state.value=='SUBMITTED_CLOSED': return
    now=time.time()
    with db.connect() as tx:
        tx.execute("UPDATE reminder_jobs SET status='cancelled' WHERE workspace=? AND notice_id=? AND status<>'sent'",(db.scope.get(),d.id))
        if not db.preferences()['email_reminders']: return
        owner=tx.execute('SELECT owner_id FROM workspaces WHERE id=?',(db.scope.get(),)).fetchone()
        if not owner: return
        for offset in (7,3,1):
            due=datetime.combine(date.fromisoformat(d.limitation.effective_legal_deadline)-timedelta(days=offset),day_time(9),ZoneInfo('Asia/Kolkata')).timestamp()
            if due<=now: continue
            job_id=hashlib.sha256(f'{db.scope.get()}:{d.id}:{due}'.encode()).hexdigest()
            tx.execute("INSERT INTO reminder_jobs VALUES (?,?,?,?,?,'pending',0,?,0) ON CONFLICT(id) DO UPDATE SET status=CASE WHEN reminder_jobs.status='cancelled' THEN 'pending' ELSE reminder_jobs.status END",(job_id,db.scope.get(),d.id,owner['owner_id'],due,due))

@router.get('/workspace/operations')
def operations():
    auth.owner()
    from app.operations import readiness
    # Business users see delivery status scoped to their workspace, never global counts.
    status=readiness()
    with db.connect() as tx:
        failed=tx.execute("SELECT COUNT(*) AS count FROM reminder_jobs WHERE workspace=? AND status='failed'",(db.scope.get(),)).fetchone()['count']
    return {'worker_age_seconds':status['worker_age_seconds'],'email_configured':status['smtp_configured'],'failed_reminders':failed}

@router.post('/notices/{notice_id}/acknowledgement')
async def acknowledgement(notice_id:str,file:UploadFile=File(...)):
    auth.writable(); d=notice_or_404(notice_id); open_case(d)
    from app.main import read_upload
    from app.uploads import validate_upload
    from pathlib import Path
    from fastapi.concurrency import run_in_threadpool
    content=await read_upload(file)
    name=Path(file.filename or 'receipt.txt').name
    await run_in_threadpool(validate_upload,content,name)
    await run_in_threadpool(db.save_evidence,d.id,'submission-proof',name,content)
    d.submission_proof_name=name; d.submission_receipt=None; d.submitted_at=None
    return db.save(d,'submission.proof_attached')


@router.get('/notices/{notice_id}/ocr/pages/{page_number}.png')
def ocr_page(notice_id:str,page_number:int):
    d=notice_or_404(notice_id)
    if page_number<1 or page_number>12: raise HTTPException(404,'Page not found.')
    original=db.evidence_document(d.id,'original')
    if not original: raise HTTPException(404,'Original retention was disabled for this upload. Reselect your source locally to inspect it.')
    name,content=original
    from app.engines.document_reader import _render_pdf,normalized_image,image_bytes
    if name.lower().endswith('.pdf'):
        pages=_render_pdf(content,only_page=page_number)
        image=pages[0]
    else:
        if page_number!=1: raise HTTPException(404,'Page not found.')
        try: image=image_bytes(normalized_image(content))
        except Exception: raise HTTPException(415,'This source is text-only and has no image preview.') from None
    return Response(image,media_type='image/png',headers={'Content-Disposition':'inline; filename="notice-page.png"'})
