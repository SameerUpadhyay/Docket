"""Real authenticated intake, crypto checks, isolation and privacy regression tests."""
import base64,hashlib,hmac,json,time,uuid
from email.message import EmailMessage
from email import policy
from io import BytesIO
from zipfile import ZipFile
import pytest
import dkim
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient
from app.main import app
from app import config,mail
from app.models import database as db
from app.email_pipeline import processor,email_router,store,arc_header_forensics
from app.email_pipeline.schemas_email import InboundEmail,normalize
from app.engines.triage_llm import local_triage
from app.engines.pii_scrubber import scrub_pii_before_llm
from test_accounts import create

SECRET='test-only-webhook-secret-'+('a'*32)
PREFIX='/api/v1/email'

@pytest.fixture
def intake(monkeypatch):
    monkeypatch.setattr(config,'DEMO_MODE',False)
    monkeypatch.setenv('INBOUND_EMAIL_DOMAIN','mail.example.com')
    monkeypatch.setenv('INBOUND_EMAIL_PROVIDER','hmac')
    monkeypatch.setenv('INBOUND_WEBHOOK_SECRET',SECRET)
    monkeypatch.setenv('INBOUND_INLINE_WORKER','0')
    messages=[]
    monkeypatch.setattr(mail,'send_email',lambda *args:messages.append(args))
    # Each test models a different client, without weakening production throttles.
    with TestClient(app,client=('email-test-'+uuid.uuid4().hex,50000)) as client:
        _,password,headers=create(client,messages,'email-owner')
        response=client.post(PREFIX+'/routing',headers=headers,json={'consent':True})
        assert response.status_code==200,response.text
        yield client,messages,headers,response.json(),password

def payload(route,**values):
    return {'From':'CGST Office <notice@cbic.gov.in>','To':route['address'],'OriginalRecipient':route['address'],
        'Subject':'Form GST ASMT-10','MessageID':uuid.uuid4().hex,'TextBody':'Form GST ASMT-10 CGST Section 61. PAN ABCDE1234F. Total demand: INR 25000.',
        'Headers':[],'Attachments':[],**values}

def deliver(client,body,secret=SECRET,timestamp=None,**headers):
    raw=json.dumps(body).encode(); stamp=str(int(time.time()) if timestamp is None else timestamp)
    signature=hmac.new(secret.encode(),stamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
    return client.post(PREFIX+'/inbound-webhook',content=raw,headers={'Content-Type':'application/json','X-Docket-Timestamp':stamp,'X-Docket-Signature':'v1='+signature,**headers})

def cases(client,headers):
    response=client.get('/api/notices',headers=headers)
    assert response.status_code==200,response.text
    return response.json()

@pytest.fixture(scope='module')
def signing_key():
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    private=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.TraditionalOpenSSL,serialization.NoEncryption())
    public=key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    return private,b'v=DKIM1; k=rsa; p='+base64.b64encode(public)

def signed_message(route,private,sender='forwarding-noreply@google.com',text=None):
    message=EmailMessage(policy=policy.SMTP)
    message['From']=sender; message['To']=route['address']; message['Subject']='Gmail forwarding confirmation'
    message.set_content(text or ('Forwarding destination: '+route['address']+'\nConfirmation code: 84920144\nhttps://mail-settings.google.com/mail/vf-test-confirm'))
    raw=message.as_bytes(); domain=sender.rsplit('@',1)[1].encode()
    return dkim.sign(raw,b'test',domain,private,include_headers=[b'from',b'to',b'subject'])+raw

def test_webhook_rejects_missing_stale_or_tampered_auth(intake):
    client,_,_,route,_=intake; value=payload(route)
    assert client.post(PREFIX+'/inbound-webhook',json=value).status_code==401
    assert deliver(client,value,secret='wrong').status_code==401
    assert deliver(client,value,timestamp=int(time.time())-600).status_code==401
    assert deliver(client,value,timestamp=int(time.time())+600).status_code==401

def test_unknown_recipient_never_creates_workspace(intake):
    client,_,_,route,_=intake
    assert deliver(client,payload(route,OriginalRecipient='u_unknown@mail.example.invalid')).status_code==404
    assert deliver(client,payload(route,OriginalRecipient='u_unknown@mail.example.invalid,second@example.invalid')).status_code==422

def test_real_signed_gmail_verification_is_private_and_expiring(intake,monkeypatch,signing_key):
    client,messages,owner,route,_=intake; private,public=signing_key
    monkeypatch.setattr(arc_header_forensics,'_dns_lookup',lambda:lambda name,timeout=2:public)
    raw=signed_message(route,private)
    value=payload(route,RawEmail=base64.b64encode(raw).decode(),TextBody='Ignored JSON text',From='attacker@example.invalid')
    result=deliver(client,value)
    assert result.status_code==202,result.text
    assert '84920144' not in result.text
    verification=client.get(PREFIX+'/verification',headers=owner).json()['verification']
    assert verification['confirmation_code']=='84920144' and not verification['auto_verified'] and not verification['simulation']
    assert verification['confirmation_url'].startswith('https://mail-settings.google.com/mail/vf-')
    assert cases(client,owner)==[]
    _,_,other=create(client,messages,'other-email')
    assert client.get(PREFIX+'/verification',headers=other).json()['verification'] is None
    with db.connect() as tx:
        record=tx.execute('SELECT payload FROM email_verifications WHERE workspace=?',(client.get('/api/auth/me',headers=owner).json()['workspace']['id'],)).fetchone()
        assert '84920144' not in record['payload']
        tx.execute('UPDATE email_verifications SET expires=? WHERE workspace=?',(time.time()-1,client.get('/api/auth/me',headers=owner).json()['workspace']['id']))
    assert client.get(PREFIX+'/verification',headers=owner).json()['verification'] is None

def test_forged_headers_cannot_produce_a_verified_sender_or_google_code(intake):
    client,_,owner,route,_=intake
    fake=[{'Name':'ARC-Authentication-Results','Value':'i=1; mx.google.com; dkim=pass header.d=google.com; spf=pass'}]
    value=payload(route,From='forwarding-noreply@google.com',TextBody='Confirmation code: 84920144',Headers=fake)
    assert deliver(client,value).status_code==202
    assert client.get(PREFIX+'/verification',headers=owner).json()['verification'] is None
    assert cases(client,owner)[0]['email_intake']['chain_forensics']['original_sender_verified'] is False

def test_dkim_tamper_and_untrusted_arc_cannot_authenticate(signing_key):
    private,public=signing_key; route={'address':'u_test@mail.example.invalid'}
    raw=signed_message(route,private,sender='notice@cbic.gov.in',text='Form GST ASMT-10. Original signed body.')
    lookup=lambda name,timeout=2:public
    assert arc_header_forensics.verify_provenance(raw,'cbic.gov.in',lookup)[0] is True
    assert arc_header_forensics.verify_provenance(raw.replace(b'Original signed body',b'Attacker changed body'),'cbic.gov.in',lookup)[0] is False
    manual=normalize(InboundEmail(From='owner@example.invalid',TextBody='---------- Forwarded message ---------\nFrom: Tax Office <notice@cbic.gov.in>\nCGST'))
    assert arc_header_forensics.unwrap_forwarded_email_forensics(manual,lookup)['original_sender_verified'] is False

def test_valid_arc_requires_trusted_sealer_and_aligned_original(signing_key):
    private,public=signing_key
    message=(b'From: Tax Office <notice@cbic.gov.in>\r\nTo: owner@example.invalid\r\nSubject: Notice\r\n'
        b'Authentication-Results: mx.google.com; dkim=pass header.d=cbic.gov.in; spf=pass smtp.mailfrom=cbic.gov.in\r\n\r\nCGST notice\r\n')
    sealed=b''.join(dkim.arc_sign(message,b'test',b'google.com',private,b'mx.google.com'))+message
    assert arc_header_forensics.verify_provenance(sealed,'cbic.gov.in',lambda name,timeout=2:public)[:2]==(True,True)
    untrusted=b''.join(dkim.arc_sign(message,b'test',b'attacker.invalid',private,b'mx.google.com'))+message
    assert arc_header_forensics.verify_provenance(untrusted,'cbic.gov.in',lambda name,timeout=2:public)[0] is False
    assert arc_header_forensics.verify_provenance(sealed,'unrelated.gov.in',lambda name,timeout=2:public)[0] is False

def test_pii_all_sources_redacted_before_optional_summary_and_no_deadline(intake,monkeypatch):
    client,_,owner,route,_=intake; seen=[]
    assert client.patch('/api/workspace/preferences',headers=owner,json={'external_ai':True}).status_code==200
    def summarize(text,issue,window,allow_external):
        seen.append((text,allow_external)); return local_triage(text,issue,window),'local-test'
    monkeypatch.setattr(processor,'triage_with_gemini',summarize)
    text='Form GST ASMT-10\nPAN ABCDE1234F\nAadhaar 4589 2310 9981\nAccount No: 004501558921\nIFSC HDFC0001234\nMobile +91-9876543210'
    assert deliver(client,payload(route,TextBody=text)).status_code==202
    dossier=cases(client,owner)[0]
    assert seen and seen[0][1] is True
    for secret in ('ABCDE1234F','4589 2310 9981','004501558921','HDFC0001234','9876543210'):
        assert secret not in seen[0][0] and secret not in dossier['redacted_ocr_excerpt']
    assert dossier['limitation'] is None and not dossier['facts_confirmed']
    assert dossier['triage']['date_of_issue_iso'] is None and dossier['triage']['response_window_days'] is None
    vault=client.get(PREFIX+'/notices/'+dossier['id']+'/pii',headers=owner)
    assert vault.status_code==200 and '004501558921' in vault.text
    restored=dossier['redacted_ocr_excerpt']
    for token,secret in vault.json()['mapping'].items(): restored=restored.replace(token,secret)
    assert 'ABCDE1234F' in restored
    with db.connect() as tx:
        row=tx.execute('SELECT payload FROM email_pii_vault WHERE notice_id=?',(dossier['id'],)).fetchone()
        assert 'ABCDE1234F' not in row['payload']

def test_retries_are_idempotent_and_ledger_events_do_not_leak_body(intake):
    client,_,owner,route,_=intake; value=payload(route)
    first=deliver(client,value); second=deliver(client,value)
    assert first.status_code==second.status_code==202
    assert first.json()['receipt_id']==second.json()['receipt_id']
    assert len(cases(client,owner))==1
    events=client.get(PREFIX+'/events',headers=owner).json()
    assert len([e for e in events['events'] if e['event']=='NEW_NOTICE_INGESTED'])==1
    assert 'ABCDE1234F' not in json.dumps(events)
    assert client.get(PREFIX+'/events?after='+events['cursor'],headers=owner).json()['events']==[]
    assert deliver(client,{**value,'TextBody':'Different content, same delivery identifier.'}).status_code==409

def test_all_attachments_screened_before_any_ocr_or_ai(intake,monkeypatch):
    client,_,owner,route,_=intake
    monkeypatch.setattr(processor,'extract_document_details',lambda *a,**k:pytest.fail('Unsafe attachments must not reach OCR'))
    monkeypatch.setattr(processor,'triage_with_gemini',lambda *a,**k:pytest.fail('Unsafe attachments must not reach AI'))
    attachments=[{'Name':'first.txt','Content':base64.b64encode(b'Form GST ASMT-10').decode()},
        {'Name':'second.pdf','Content':base64.b64encode(b'MZexecutable').decode()}]
    assert deliver(client,payload(route,Attachments=attachments)).status_code==202
    assert cases(client,owner)[0]['state']=='PHISHING_QUARANTINED'

def test_bad_base64_rejected_and_manual_phishing_quarantined(intake):
    client,_,owner,route,_=intake
    assert deliver(client,payload(route,Attachments=[{'Name':'bad.pdf','Content':'not base64'}])).status_code==422
    text='---------- Forwarded message ---------\nFrom: Income Tax Enforcement <refund@incometax-verify.example>\nSubject: Demand\n\nPay at upi://pay?pa=fraud@okaxis'
    assert deliver(client,payload(route,From='owner@example.invalid',TextBody=text)).status_code==202
    dossier=cases(client,owner)[0]
    assert dossier['state']=='PHISHING_QUARANTINED' and dossier['triage'] is None
    assert dossier['email_intake']['chain_forensics']['ingestion_mode']=='MANUAL_FORWARD'

def test_durable_worker_recovers_accepted_delivery(intake,monkeypatch):
    client,_,owner,route,_=intake
    monkeypatch.setattr(email_router,'process_receipt',lambda identifier:None)
    assert deliver(client,payload(route)).status_code==202
    assert cases(client,owner)==[]
    assert processor.process_next() is True
    assert len(cases(client,owner))==1

def test_preview_cannot_be_confirmed_or_exported_and_requires_rotation(intake,monkeypatch):
    client,_,owner,_,_=intake
    monkeypatch.delenv('INBOUND_EMAIL_DOMAIN')
    monkeypatch.delenv('INBOUND_WEBHOOK_SECRET')
    preview=client.post(PREFIX+'/routing/rotate',headers=owner,json={'consent':True}).json()
    assert preview['address'].endswith('.invalid')
    assert client.get(PREFIX+'/settings',headers=owner).json()['delivery_configured'] is False
    for path,method in (('/routing/confirm','post'),('/gmail-filter.xml','get')):
        response=getattr(client,method)(PREFIX+path,headers=owner,**({'json':{'consent':True}} if method=='post' else {}))
        assert response.status_code==409 and 'Local preview' in response.text
    monkeypatch.setenv('INBOUND_EMAIL_DOMAIN','mail.example.com')
    monkeypatch.setenv('INBOUND_WEBHOOK_SECRET',SECRET)
    assert 'Replace' in client.post(PREFIX+'/routing/confirm',headers=owner,json={'consent':True}).text
    client.post(PREFIX+'/routing/rotate',headers=owner,json={'consent':True})
    assert client.post(PREFIX+'/routing/confirm',headers=owner,json={'consent':True}).status_code==200
    assert client.get(PREFIX+'/gmail-filter.xml',headers=owner).status_code==200
    response=client.get('/api/privacy/gmail-filter.xml',headers=owner,params={'webhook_email':'o.w.n.e.r+legal@googlemail.com','source_email':'owner@gmail.com'})
    assert response.status_code==422 and 'cannot forward to itself' in response.text
    monkeypatch.setenv('INBOUND_EMAIL_DOMAIN','mail.example.invalid')
    assert store.settings()['delivery_configured'] is False


def test_rotation_disable_and_revoked_roles_are_enforced(intake):
    client,messages,owner,route,_=intake
    assert client.get(PREFIX+'/gmail-filter.xml',headers=owner).status_code==409
    assert client.post(PREFIX+'/routing/confirm',headers=owner,json={'consent':True}).status_code==200
    xml=client.get(PREFIX+'/gmail-filter.xml',headers=owner)
    assert xml.status_code==200 and route['address'] in xml.text and 'incometax.gov.in' in xml.text
    replacement=client.post(PREFIX+'/routing/rotate',headers=owner,json={'consent':True}).json()
    assert replacement['address']!=route['address']
    assert deliver(client,payload(route)).status_code==404
    _,_,reviewer=create(client,messages,'email-reviewer')
    me=client.get('/api/auth/me',headers=owner).json(); other=client.get('/api/auth/me',headers=reviewer).json()
    with db.connect() as tx: tx.execute('INSERT INTO members VALUES (?,?,?)',(me['workspace']['id'],other['user']['id'],'reviewer'))
    reviewer={**reviewer,'X-Workspace-ID':me['workspace']['id']}
    assert 'address' not in client.get(PREFIX+'/settings',headers=reviewer).json()['route']
    assert client.get(PREFIX+'/verification',headers=reviewer).status_code==403
    assert client.post(PREFIX+'/simulate',headers=reviewer,json={'scenario':'gst'}).status_code==403
    assert client.delete(PREFIX+'/routing',headers=owner).status_code==200
    assert deliver(client,payload(replacement)).status_code==404

def test_consent_withdrawn_during_processing_prevents_case_creation(intake,monkeypatch):
    client,_,owner,route,_=intake
    original=processor._build
    def withdraw(*args):
        result=original(*args); store.disable_route(); return result
    monkeypatch.setattr(processor,'_build',withdraw)
    assert deliver(client,payload(route)).status_code==202
    assert cases(client,owner)==[]

def test_export_delete_and_vault_expiry(intake):
    client,_,owner,route,password=intake
    assert deliver(client,payload(route)).status_code==202
    dossier=cases(client,owner)[0]
    exported=client.get('/api/account/export',headers=owner)
    with ZipFile(BytesIO(exported.content)) as archive:
        assert 'email/receipts.json' in archive.namelist()
        assert 'ABCDE1234F' in archive.read('email/identifiers/'+dossier['id']+'.json').decode()
    with db.connect() as tx: tx.execute('UPDATE email_pii_vault SET expires=? WHERE notice_id=?',(time.time()-1,dossier['id']))
    assert client.get(PREFIX+'/notices/'+dossier['id']+'/pii',headers=owner).status_code==410
    assert client.delete('/api/notices/'+dossier['id'],headers=owner).status_code==200
    assert client.get(PREFIX+'/notices/'+dossier['id']+'/pii',headers=owner).status_code==404
    assert deliver(client,payload(route)).status_code==202
    workspace=client.get('/api/auth/me',headers=owner).json()['workspace']['id']
    response=client.request('DELETE','/api/account',headers=owner,json={'password':password})
    assert response.status_code==200,response.text
    with db.connect() as tx:
        for table in ('email_routes','email_receipts','email_events','email_pii_vault','email_verifications'):
            assert tx.execute(f'SELECT COUNT(*) AS count FROM {table} WHERE workspace=?',(workspace,)).fetchone()['count']==0

def test_simulations_are_labelled_and_disabled_in_production(intake,monkeypatch):
    client,_,owner,route,_=intake
    assert client.post(PREFIX+'/simulate',headers=owner,json={'scenario':'verification'}).status_code==202
    assert client.get(PREFIX+'/verification',headers=owner).json()['verification']['simulation'] is True
    assert client.post(PREFIX+'/simulate',headers=owner,json={'scenario':'gst'}).status_code==202
    assert cases(client,owner)[0]['is_demo'] is True
    monkeypatch.setattr(config,'PRODUCTION',True)
    assert client.post(PREFIX+'/simulate',headers=owner,json={'scenario':'gst'}).status_code==404

def test_postmark_basic_auth(intake,monkeypatch):
    client,_,owner,route,_=intake
    monkeypatch.setenv('INBOUND_EMAIL_PROVIDER','postmark')
    monkeypatch.setenv('INBOUND_POSTMARK_USER','inbound')
    monkeypatch.setenv('INBOUND_POSTMARK_PASSWORD',SECRET)
    authorization='Basic '+base64.b64encode(('inbound:'+SECRET).encode()).decode()
    assert client.post(PREFIX+'/inbound-webhook',json=payload(route),headers={'Authorization':authorization}).status_code==200
    assert len(cases(client,owner))==1

def test_pii_overlap_roundtrip_including_ifsc():
    value='PAN ABCDE1234F; Account No: 004501558921; again 004501558921; IFSC HDFC0001234; +91-9876543210'
    safe,mapping,count=scrub_pii_before_llm(value)
    for secret in ('ABCDE1234F','004501558921','HDFC0001234','9876543210'): assert secret not in safe
    assert count==len(mapping)
    for key,secret in mapping.items(): safe=safe.replace(key,secret)
    assert safe==value

def test_bilingual_pdf_and_second_attachment_qr_are_processed_locally(intake,monkeypatch):
    from pathlib import Path
    from generate_synthetic_notices import create_bilingual_gst_drc01_pdf
    client,_,owner,route,_=intake
    assert client.patch('/api/workspace/preferences',headers=owner,json={'cloud_ocr':True}).status_code==200
    original=processor.extract_document_details; observed=[]
    def local_only(content,name,language,allow_cloud):
        observed.append(allow_cloud); return original(content,name,language,allow_cloud)
    monkeypatch.setattr(processor,'extract_document_details',local_only)
    pdf=create_bilingual_gst_drc01_pdf()
    first=payload(route,Attachments=[{'Name':'gst.pdf','Content':base64.b64encode(pdf).decode()}])
    assert deliver(client,first).status_code==202
    normal=cases(client,owner)[0]
    assert normal['ocr_analysis']['structured_triage']['specific_form_code']=='Form GST DRC-01'
    assert 'Hindi' in normal['ocr_analysis']['structured_triage']['detected_languages']
    assert normal['limitation'] is None
    qr=(Path(__file__).parent/'fixtures'/'scam-qr.png').read_bytes()
    second=payload(route,Attachments=[{'Name':'first.txt','Content':base64.b64encode(b'ASMT-10 CGST notice').decode()},
        {'Name':'second.png','Content':base64.b64encode(qr).decode()}])
    assert deliver(client,second).status_code==202
    assert any(d['state']=='PHISHING_QUARANTINED' for d in cases(client,owner))
    assert observed and not any(observed)

def test_stream_replay_and_session_revocation(intake):
    import asyncio
    from types import SimpleNamespace
    client,_,owner,route,_=intake
    assert deliver(client,payload(route)).status_code==202
    identity=client.get('/api/auth/me',headers=owner).json()
    workspace=identity['workspace']['id']
    class Connection:
        state=SimpleNamespace(user=identity['user'],token=owner['Authorization'][7:])
        async def is_disconnected(self): return False
    async def verify():
        token=db.scope.set(workspace)
        try:
            response=await email_router.stream(Connection())
            iterator=response.body_iterator
            assert 'retry:' in await anext(iterator)
            frame=await anext(iterator)
            assert 'NEW_NOTICE_INGESTED' in frame and 'ABCDE1234F' not in frame
            client.post('/api/auth/logout-all',headers=owner)
            assert 'ACCESS_REVOKED' in await anext(iterator)
            await iterator.aclose()
        finally: db.scope.reset(token)
    asyncio.run(verify())

def test_screening_failure_retries_without_publishing_a_case(intake,monkeypatch):
    from fastapi import HTTPException
    client,_,owner,route,_=intake
    def unavailable(*args): raise HTTPException(503,'Scanner unavailable')
    monkeypatch.setattr(processor,'validate_upload',unavailable)
    response=deliver(client,payload(route,Attachments=[{'Name':'notice.txt','Content':base64.b64encode(b'ASMT-10 notice').decode()}]))
    assert response.status_code==202 and cases(client,owner)==[]
    receipt=client.get(PREFIX+'/receipts',headers=owner).json()[0]
    assert receipt['status']=='retry' and receipt['error_code']=='screening-unavailable'
    with db.connect() as tx:
        queued=tx.execute('SELECT payload FROM email_receipts WHERE id=?',(receipt['id'],)).fetchone()
        assert 'ASMT-10' not in queued['payload']
    assert client.delete(PREFIX+'/routing',headers=owner).status_code==200
    with db.connect() as tx:
        cancelled=tx.execute('SELECT payload,status FROM email_receipts WHERE id=?',(receipt['id'],)).fetchone()
        assert cancelled['payload']=='' and cancelled['status']=='cancelled'

def test_queue_backpressure_keeps_retries_idempotent(intake,monkeypatch):
    client,_,owner,route,_=intake
    monkeypatch.setattr(email_router,'process_receipt',lambda identifier:None)
    messages=[payload(route) for _ in range(21)]
    for value in messages[:20]: assert deliver(client,value).status_code==202
    assert deliver(client,messages[20]).status_code==429
    assert deliver(client,messages[0]).status_code==202
    assert client.delete(PREFIX+'/routing',headers=owner).status_code==200
