"""Authenticated provider intake, owner onboarding, and workspace event streams."""
import asyncio,base64,binascii,hashlib,hmac,json,os,time,uuid
from fastapi import APIRouter,BackgroundTasks,HTTPException,Request
from fastapi.responses import Response,StreamingResponse,JSONResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError
from app import auth,config
from app.models import database as db
from app.engines.gmail_filter_gen import generate_gmail_filter_xml,FILTER_QUERY
from . import store
from .schemas_email import InboundEmail,Consent,Simulation,normalize,one_address
from .processor import process_receipt

router=APIRouter(prefix='/api/v1/email',tags=['Selective email forwarding'])

def _member(request): auth.current(request)

def _authenticate_provider(request,body):
    options=store.settings()
    if not options['delivery_configured']: raise HTTPException(503,'Incoming email delivery is not configured.')
    if options['provider']=='hmac':
        timestamp=request.headers.get('x-docket-timestamp','')
        if not timestamp.isdigit() or len(timestamp)>12 or abs(time.time()-int(timestamp))>300:
            raise HTTPException(401,'Invalid webhook authentication.')
        expected=hmac.new(os.environ['INBOUND_WEBHOOK_SECRET'].encode(),timestamp.encode()+b'.'+body,hashlib.sha256).hexdigest()
        supplied=request.headers.get('x-docket-signature','').removeprefix('v1=')
        if not hmac.compare_digest(expected,supplied): raise HTTPException(401,'Invalid webhook authentication.')
    elif options['provider']=='postmark':
        header=request.headers.get('authorization','')
        try:
            if not header.startswith('Basic '): raise ValueError()
            supplied=base64.b64decode(header[6:],validate=True).decode()
            expected=os.environ['INBOUND_POSTMARK_USER']+':'+os.environ['INBOUND_POSTMARK_PASSWORD']
            if not hmac.compare_digest(supplied.encode(),expected.encode()): raise ValueError()
        except (ValueError,UnicodeError,binascii.Error): raise HTTPException(401,'Invalid webhook authentication.')
    else: raise HTTPException(503,'Incoming email provider is not supported.')

@router.post('/inbound-webhook',status_code=202)
async def webhook(request:Request,background:BackgroundTasks):
    body=await request.body()
    _authenticate_provider(request,body)
    try: payload=InboundEmail.model_validate_json(body)
    except ValidationError: raise HTTPException(422,'Invalid or oversized inbound email payload.')
    address=one_address(payload.OriginalRecipient or payload.To)
    normalize(payload) # Bound MIME/decoded bytes before accepting a delivery.
    identifier,status=await run_in_threadpool(store.enqueue,payload,address)
    background.add_task(process_receipt,identifier)
    # Never return confirmation codes, subject text, PII or routing tokens here.
    return JSONResponse({'status':'accepted','receipt_id':identifier,'delivery_status':status},
        status_code=200 if store.settings()['provider']=='postmark' else 202)

@router.get('/settings')
def settings(request:Request):
    _member(request); options=store.settings()
    current=store.route()
    if db.role.get()!='owner' and current: current={k:v for k,v in current.items() if k!='address'}
    with db.connect() as tx:
        state=tx.execute('SELECT last_checked,error_code FROM email_agentmail_state WHERE route_id=?',(current['id'],)).fetchone() if current else None
    return {'delivery_configured':options['delivery_configured'],'provider':options['provider'],
        'connection':dict(state) if state else None,'fixed_receiving_address':options['provider']=='agentmail',
        'simulator_enabled':options['simulator_enabled'] and db.role.get()=='owner','route':current,
        'mailbox_access_requested':False,'confirmation_required':True,'filter_query':FILTER_QUERY}

@router.post('/routing')
def enable(request:Request,body:Consent):
    _member(request); auth.owner()
    if not body.consent: raise HTTPException(422,'Confirm that you control the mailbox and may forward these notices.')
    return store.enable_route()

@router.post('/routing/rotate')
def rotate(request:Request,body:Consent):
    _member(request); auth.owner()
    if not body.consent: raise HTTPException(422,'Confirm address rotation and update your mail rules afterward.')
    return store.enable_route(rotate=True)

@router.delete('/routing')
def disable(request:Request):
    _member(request); auth.owner(); store.disable_route()
    return {'message':'Receiving disabled. Remove the forwarding rule in your mailbox too; already-created cases are kept until deleted.'}

@router.post('/routing/confirm')
def confirm(request:Request,body:Consent):
    _member(request); auth.owner(); current=store.route()
    _require_live_destination(current)
    if not current or not current['enabled']: raise HTTPException(409,'Enable a receiving address first.')
    if not body.consent: raise HTTPException(422,'Confirm that forwarding was verified in your mailbox.')
    with db.connect() as tx:
        tx.execute('UPDATE email_routes SET confirmed_at=? WHERE workspace=? AND id=? AND enabled=1',(time.time(),db.scope.get(),current['id']))
        db.event('','email.forwarding.confirmed_by_owner',db=tx)
    return store.route()

@router.get('/verification')
def verification(request:Request):
    _member(request); auth.owner()
    return {'verification':store.verification()}

@router.get('/gmail-filter.xml')
def gmail_filter(request:Request):
    _member(request); auth.owner(); current=store.route()
    _require_live_destination(current)
    if not current or not current['enabled'] or not current['confirmed_at']:
        raise HTTPException(409,'Confirm the forwarding destination in Gmail before downloading its filter.')
    return Response(generate_gmail_filter_xml(current['address']),media_type='application/xml',
        headers={'Content-Disposition':'attachment; filename="docket-selective-mail-filter.xml"'})

def _require_live_destination(current):
    options=store.settings()
    if not options['delivery_configured']:
        raise HTTPException(409,'Local preview cannot receive Gmail messages. Configure an inbound provider and receiving address before confirming forwarding or downloading a Gmail filter.')
    if current:
        address=current['address']
        matches=(address==options['agentmail_address'] if options['provider']=='agentmail' else address.startswith(options['base'].split('@')[0]+'+u_') and address.endswith('@inbound.postmarkapp.com') if options['base'] else address.endswith('@'+options['domain']))
        if not matches:
            raise HTTPException(409,'The receiving configuration changed. Replace the preview or old address, then verify the new destination in Gmail.')

@router.get('/events')
def events(request:Request,after:str=''):
    _member(request)
    if len(after)>64: raise HTTPException(422,'Invalid event cursor.')
    records=store.events(after)
    return {'events':records,'cursor':records[-1]['id'] if records else after}

@router.get('/stream')
async def stream(request:Request,after:str=''):
    user=auth.current(request); workspace=db.scope.get(); token=request.state.token
    if len(after)>64: raise HTTPException(422,'Invalid event cursor.')
    async def generate():
        cursor=after; started=time.monotonic(); heartbeat=started
        scope_token=db.scope.set(workspace)
        try:
            yield 'retry: 2000\n\n'
            while time.monotonic()-started<55:
                if await request.is_disconnected(): break
                try:
                    await run_in_threadpool(auth.identity,token)
                    await run_in_threadpool(auth.workspace,user['id'],workspace)
                except HTTPException:
                    yield 'event: ACCESS_REVOKED\ndata: {}\n\n'; break
                records=await run_in_threadpool(store.events,cursor)
                for event in records:
                    cursor=event['id']
                    yield 'id: '+cursor+'\nevent: '+event['event']+'\ndata: '+json.dumps(event['data'])+'\n\n'
                if time.monotonic()-heartbeat>10:
                    yield ': keep-alive\n\n'; heartbeat=time.monotonic()
                await asyncio.sleep(.5)
        finally: db.scope.reset(scope_token)
    return StreamingResponse(generate(),media_type='text/event-stream',headers={'X-Accel-Buffering':'no','Cache-Control':'no-store','Content-Encoding':'identity'})

@router.get('/receipts')
def receipts(request:Request):
    _member(request); auth.owner()
    with db.connect() as tx:
        records=tx.execute('SELECT id,status,notice_id,created_at,error_code,simulation FROM email_receipts WHERE workspace=? ORDER BY created_at DESC LIMIT 30',(db.scope.get(),)).fetchall()
    return [dict(r) for r in records]

@router.get('/notices/{notice_id}/pii')
def pii(request:Request,notice_id:str):
    _member(request); auth.writable()
    if not db.get(notice_id): raise HTTPException(404,'Notice not found.')
    with db.connect() as tx:
        store.cleanup(tx)
        row=tx.execute('SELECT payload,expires FROM email_pii_vault WHERE workspace=? AND notice_id=?',(db.scope.get(),notice_id)).fetchone()
    if not row: raise HTTPException(410,'The temporary identifier vault has expired or was deleted.')
    return {'mapping':json.loads(db.unseal(row['payload'])),'expires_at':row['expires']}

@router.post('/simulate',status_code=202)
def simulate(request:Request,body:Simulation,background:BackgroundTasks):
    _member(request); auth.owner()
    if config.PRODUCTION: raise HTTPException(404,'Not found.')
    auth.throttle('email-simulator:'+db.scope.get(),20,60)
    current=store.route()
    if not current or not current['enabled']: raise HTTPException(409,'Enable a local preview receiving address first.')
    sender='CGST sample <range@example.gov.in>'
    subject='FICTIONAL TEST · Form GST ASMT-10'
    text='FICTIONAL TEST ONLY\nForm GST ASMT-10, Section 61 CGST\nPAN ABCDE1234F\nAccount No: 004501558921\nIFSC HDFC0001234\nTotal demand: INR 25,000\nPlease respond within 30 days.'
    if body.scenario=='verification':
        sender='Gmail simulation <forwarding-noreply@google.com>'; subject='FICTIONAL TEST · Gmail forwarding confirmation'
        text='Simulation only. Confirmation code: 84920144\nForwarding to '+current['address']
    elif body.scenario=='legal':
        sender='Owner <owner@example.invalid>'; subject='FICTIONAL TEST · forwarded Section 138 demand'
        text='---------- Forwarded message ---------\nFrom: Advocate <advocate@example.invalid>\nSubject: Section 138 NI Act\n\nFICTIONAL TEST. Cheque dishonoured. Total demand: INR 350000. Respond within 15 days.'
    elif body.scenario=='phishing':
        sender='GST Compliance Cell <urgent@gst-verify-payments.example>'; subject='FICTIONAL TEST · spoofed tax demand'
        text='FICTIONAL TEST. CGST. Pay now at upi://pay?pa=fraud@okaxis and share your OTP.'
    attachments=[]
    if body.scenario=='gst':
        from io import BytesIO
        from reportlab.pdfgen.canvas import Canvas
        output=BytesIO(); pdf=Canvas(output)
        for index,line in enumerate(text.splitlines()): pdf.drawString(50,780-index*28,line)
        pdf.save(); content=output.getvalue()
        attachments=[{'Name':'fictional-gst.pdf','Content':base64.b64encode(content).decode(),'ContentType':'application/pdf','ContentLength':len(content)}]
    payload=InboundEmail(From=sender,To=current['address'],OriginalRecipient=current['address'],MessageID='simulation-'+uuid.uuid4().hex,Subject=subject,TextBody=text,Attachments=attachments)
    identifier,status=store.enqueue(payload,current['address'],simulation=True)
    background.add_task(process_receipt,identifier)
    return {'status':'accepted','receipt_id':identifier,'delivery_status':status,'simulation':True}
