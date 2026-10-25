"""Security tests use real authentication, independent users and actual encrypted persistence."""
import json,time,uuid
from io import BytesIO
from zipfile import ZipFile
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import config,auth,mail
from app.models import database as db
from app.workers import delivery

@pytest.fixture
def secured(monkeypatch):
    monkeypatch.setattr(config,'DEMO_MODE',False)
    messages=[]
    monkeypatch.setattr(mail,'send_email',lambda address,subject,text: messages.append((address,subject,text)))
    with TestClient(app) as client: yield client,messages

def create(client,messages,prefix='owner'):
    email=f'{prefix}-{uuid.uuid4().hex[:8]}@example.in'; password='Correct horse battery staple!'
    response=client.post('/api/auth/register',json={'email':email,'password':password,'name':prefix,'business':prefix+' business','consent':True})
    assert response.status_code==200,response.text
    import re
    code=re.search(r'code is (\d{8})',messages[-1][2]).group(1)
    assert client.post('/api/auth/login',json={'email':email,'password':password}).status_code==401
    assert client.post('/api/auth/verify',json={'email':email,'code':code}).status_code==200
    response=client.post('/api/auth/login',json={'email':email,'password':password})
    assert response.status_code==200,response.text
    token=response.json()['access_token']
    return email,password,{'Authorization':'Bearer '+token}

def upload(client,headers):
    response=client.post('/api/notices/analyze',headers=headers,files={'file':('notice.txt',b'ASMT-10 CGST Section 61\nTotal demand: INR 25,000\nPAN ABCDE1234F','text/plain')},data={'date_of_issue':'2026-10-24','date_of_service':'2026-10-25','window_days':30})
    assert response.status_code==200,response.text
    return response.json()

def test_auth_ownership_exports_and_encryption(secured):
    client,messages=secured
    assert client.get('/api/notices').status_code==401
    _,_,owner=create(client,messages)
    assert client.get('/api/notices',headers=owner).json()==[]
    notice=upload(client,owner); case=notice['id']
    assert notice['source_sha256'] and not notice['facts_confirmed']
    with db.connect() as tx:
        value=tx.execute('SELECT dossier FROM cases_v2 WHERE id=?',(case,)).fetchone()['dossier']
        assert '25,000' not in value and 'CGST' not in value and value.startswith('gAAAA')
    _,_,other=create(client,messages,'stranger')
    assert client.get('/api/notices',headers=other).json()==[]
    paths=[f'/api/notices/{case}/report.pdf',f'/api/notices/{case}/reply.pdf',f'/api/notices/{case}/history']
    for path in paths: assert client.get(path,headers=other).status_code==404
    assert client.patch(f'/api/notices/{case}/draft',headers=other,json={'draft_reply':'steal'}).status_code==404
    package=client.get('/api/account/export',headers=owner)
    assert package.status_code==200
    with ZipFile(BytesIO(package.content)) as archive: assert f'cases/{case}/dossier.json' in archive.namelist()

def test_invitation_roles_and_immediate_revocation(secured):
    client,messages=secured
    owner_email,_,owner=create(client,messages)
    reviewer_email,_,reviewer=create(client,messages,'advisor')
    case=upload(client,owner)['id']
    workspace=client.get('/api/auth/me',headers=owner).json()['workspace']['id']
    assert client.post('/api/workspace/invitations',headers=owner,json={'email':reviewer_email,'role':'reviewer'}).status_code==200
    token=messages[-1][2].split('\n\n')[1]
    assert client.post('/api/workspace/invitations/accept',headers=reviewer,json={'token':token}).status_code==200
    shared=reviewer|{'X-Workspace-ID':workspace}
    assert len(client.get('/api/notices',headers=shared).json())==1
    assert client.patch(f'/api/notices/{case}/draft',headers=shared,json={'draft_reply':'unauthorized'}).status_code==403
    assert client.post(f'/api/notices/{case}/reviews',headers=shared,json={'decision':'COMMENT','comment':'Please confirm the original service record.'}).status_code==200
    assert client.get('/api/account/export',headers=shared).status_code==403
    user_id=client.get('/api/auth/me',headers=reviewer).json()['user']['id']
    assert client.delete('/api/workspace/members/'+user_id,headers=owner).status_code==200
    assert client.get('/api/notices',headers=shared).status_code==403

def test_reset_revokes_sessions_and_one_time_codes(secured):
    client,messages=secured
    email,_,headers=create(client,messages)
    assert client.post('/api/auth/forgot',json={'email':email}).status_code==200
    import re
    code=re.search(r'code is (\d{8})',messages[-1][2]).group(1)
    body={'email':email,'code':code,'password':'New long secure password!'}
    assert client.post('/api/auth/reset',json=body).status_code==200
    assert client.get('/api/notices',headers=headers).status_code==401
    assert client.post('/api/auth/reset',json=body).status_code==400

def test_csrf_and_logout(secured):
    client,messages=secured; _,_,headers=create(client,messages)
    assert client.patch('/api/workspace/preferences',json={}).status_code==403
    assert client.patch('/api/workspace/preferences',headers=headers|{'Origin':'https://evil.example'},json={}).status_code==403
    assert client.post('/api/auth/logout',headers=headers).status_code==200
    assert client.get('/api/notices',headers=headers).status_code==401

def test_review_submission_and_reminder_pipeline(secured):
    client,messages=secured; _,_,headers=create(client,messages)
    d=upload(client,headers); case=d['id']
    assert client.patch(f'/api/notices/{case}/state',headers=headers,json={'state':'SUBMITTED_CLOSED'}).status_code==409
    assert client.post(f'/api/notices/{case}/reviews',headers=headers,json={'decision':'REVIEWED','comment':'Reviewed against original documents.'}).status_code==409
    assert client.patch('/api/workspace/preferences',headers=headers,json={'email_reminders':True}).status_code==200
    facts={'issue':'2026-10-24','service':'2026-10-25','window':30,'amount':25000,'authority':'Confirmed authority','section':'CGST Section 61','basis':'Checked service acknowledgement and original notice.'}
    assert client.patch(f'/api/notices/{case}/facts',headers=headers,json=facts).status_code==200
    jobs=client.get('/api/watchdog',headers=headers).json()['jobs']
    assert len(jobs)==3
    assert client.post(f'/api/notices/{case}/reviews',headers=headers,json={'decision':'REVIEWED','comment':'Reviewed originals, dates and proposed response.'}).status_code==200
    assert client.post(f'/api/notices/{case}/acknowledgement',headers=headers,files={'file':('receipt.txt',b'Official submission acknowledgement ACK123456')}).status_code==200
    assert client.post(f'/api/notices/{case}/submission',headers=headers,json={'acknowledgement':'ACK123456','submitted_at':'2026-10-25','channel':'Official portal'}).status_code==200
    assert client.patch(f'/api/notices/{case}/state',headers=headers,json={'state':'SUBMITTED_CLOSED'}).status_code==200
    assert all(j['status']=='cancelled' for j in client.get('/api/watchdog',headers=headers).json()['jobs'])
    history=client.get(f'/api/notices/{case}/history',headers=headers).json()
    assert any(h['event']=='facts.confirmed' for h in history)

def test_deletion_cascades_and_stops_access(secured):
    client,messages=secured; _,password,headers=create(client,messages)
    d=upload(client,headers)
    assert client.request('DELETE','/api/account',headers=headers,json={'password':'wrong'}).status_code==401
    assert client.request('DELETE','/api/account',headers=headers,json={'password':password}).status_code==200
    assert client.get('/api/notices',headers=headers).status_code==401
    with db.connect() as tx: assert not tx.execute('SELECT id FROM cases_v2 WHERE id=?',(d['id'],)).fetchone()

def test_delivery_retries_and_no_document_content(secured):
    client,messages=secured; _,_,headers=create(client,messages)
    d=upload(client,headers)
    workspace=client.get('/api/auth/me',headers=headers).json()['workspace']['id']
    user_id=client.get('/api/auth/me',headers=headers).json()['user']['id']
    client.patch('/api/workspace/preferences',headers=headers,json={'email_reminders':True})
    with db.connect() as tx: tx.execute("INSERT INTO reminder_jobs VALUES (?,?,?,?,?,'pending',0,?,0)",(uuid.uuid4().hex,workspace,d['id'],user_id,time.time()-10,time.time()-10))
    delivery.tick()
    assert 'no document' in messages[-1][2].lower()
    assert 'ABCDE1234F' not in messages[-1][2] and '25,000' not in messages[-1][2]

def test_production_configuration_fails_closed(monkeypatch):
    monkeypatch.setattr(config,'PRODUCTION',True); monkeypatch.setattr(config,'DATABASE_URL','')
    with pytest.raises(RuntimeError,match='PostgreSQL'): config.validate_production()


def test_draft_conflicts_preserve_versions_and_invalidate_review(secured):
    client,messages=secured; _,_,headers=create(client,messages)
    d=upload(client,headers); case=d['id']
    first=client.patch(f'/api/notices/{case}/draft',headers=headers,json={'draft_reply':'First reviewed facts','expected_revision':d['revision']})
    assert first.status_code==200
    conflict=client.patch(f'/api/notices/{case}/draft',headers=headers,json={'draft_reply':'Stale overwrite','expected_revision':d['revision']})
    assert conflict.status_code==409
    assert client.get('/api/notices',headers=headers).json()[0]['draft_reply']=='First reviewed facts'
    history=client.get(f'/api/notices/{case}/history',headers=headers).json()
    assert any(h['event']=='draft.saved' and 'previous_draft' in h['details'] for h in history)


def test_encrypted_object_storage_and_deletion_outbox(secured,monkeypatch):
    client,messages=secured; _,_,headers=create(client,messages)
    from app import objects
    class FakeBody(BytesIO): pass
    class FakeS3:
        def __init__(self): self.files={}
        def put_object(self,**kwargs):
            assert kwargs['ServerSideEncryption']=='AES256'
            self.files[kwargs['Key']]=kwargs['Body']
        def get_object(self,**kwargs): return {'Body':FakeBody(self.files[kwargs['Key']])}
        def delete_object(self,**kwargs): self.files.pop(kwargs['Key'],None)
    fake=FakeS3(); monkeypatch.setenv('OBJECT_BUCKET','private-test-bucket'); monkeypatch.setattr(objects,'client',lambda:fake)
    d=upload(client,headers); case=d['id']
    response=client.post(f'/api/notices/{case}/evidence/doc-1',headers=headers,files={'file':('evidence.txt',b'Private evidence contents')})
    assert response.status_code==200,response.text
    assert len(fake.files)==1 and b'Private evidence contents' not in list(fake.files.values())[0]
    package=client.post(f'/api/notices/{case}/export-ca-brief',headers=headers)
    with ZipFile(BytesIO(package.content)) as archive: assert archive.read('evidence/01-doc-1.txt')==b'Private evidence contents'
    assert client.delete(f'/api/notices/{case}',headers=headers).status_code==200
    objects.collect()
    assert not fake.files


def test_wrong_file_type_and_scanner_fail_closed(secured,monkeypatch):
    client,messages=secured; _,_,headers=create(client,messages)
    data={'date_of_issue':'2026-10-24','date_of_service':'2026-10-25','window_days':30}
    assert client.post('/api/notices/analyze',headers=headers,files={'file':('fake.pdf',b'not really a pdf')},data=data).status_code==422
    monkeypatch.setattr(config,'PRODUCTION',True)
    from app.uploads import validate_upload
    from fastapi import HTTPException
    monkeypatch.delenv('CLAMAV_HOST',raising=False)
    with pytest.raises(HTTPException) as rejected: validate_upload(b'plain text notice','notice.txt')
    assert rejected.value.status_code==503


def test_ses_delivery_uses_workload_client_and_configuration_set(monkeypatch):
    import boto3
    sent=[]
    class FakeSes:
        def send_email(self,**kwargs): sent.append(kwargs)
    monkeypatch.setattr(config,'MAIL_TRANSPORT','ses')
    monkeypatch.setattr(config,'SES_CONFIGURATION_SET','pilot-mail')
    monkeypatch.setattr(boto3,'client',lambda service,**kwargs: FakeSes())
    mail.send_email('owned-test@example.in','Verification test','Synthetic verification only')
    assert sent[0]['Destination']['ToAddresses']==['owned-test@example.in']
    assert sent[0]['ConfigurationSetName']=='pilot-mail'
    assert b'Synthetic verification only' in sent[0]['Content']['Raw']['Data']


def test_chunked_multipart_request_has_hard_body_limit(secured):
    client,messages=secured; _,_,headers=create(client,messages)
    def body():
        yield b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="oversize.txt"\r\nContent-Type: text/plain\r\n\r\n'
        for _ in range(13): yield b'x'*(1024*1024)
        yield b'\r\n--boundary--\r\n'
    response=client.post('/api/notices/analyze',headers=headers|{'Content-Type':'multipart/form-data; boundary=boundary'},content=body())
    assert response.status_code==413,response.text


def test_legacy_prototype_is_preserved_in_encrypted_unassigned_archive():
    import sqlite3
    if config.DATABASE_URL: pytest.skip('Legacy prototype migration applies only to SQLite')
    with db.connect() as tx:
        tx.execute('CREATE TABLE notices (id TEXT PRIMARY KEY,dossier TEXT NOT NULL)')
        tx.execute('INSERT INTO notices VALUES (?,?)',('legacy-private-record','{"private":"Legacy confidential value"}'))
    db.migrate()
    with db.connect() as tx:
        archived=tx.execute('SELECT payload FROM legacy_archive WHERE id=?',('notice:legacy-private-record',)).fetchone()['payload']
        assert 'Legacy confidential value' not in archived
        assert json.loads(db.unseal(archived))['private']=='Legacy confidential value'
        assert not tx.execute("SELECT name FROM sqlite_master WHERE name='notices'").fetchone()


def test_ocr_preview_source_retention_and_cross_business_access(secured):
    from app.engines.document_reader import tesseract_command
    if not tesseract_command(): pytest.skip('Install the local OCR runtime for authenticated source-preview acceptance')
    from generate_synthetic_notices import create_bilingual_gst_drc01_pdf
    client,messages=secured
    payload=create_bilingual_gst_drc01_pdf()
    assert client.post('/api/ocr/ingest-and-triage',files={'file':('notice.pdf',payload)}).status_code==401
    _,_,owner=create(client,messages)
    assert client.patch('/api/workspace/preferences',headers=owner,json={'retain_original':True,'cloud_ocr':False}).status_code==200
    preview=client.post('/api/ocr/ingest-and-triage',headers=owner,files={'file':('notice.pdf',payload)})
    assert preview.status_code==200,preview.text
    assert preview.json()['structured_triage']['total_demand_inr']=='160000.00'
    assert client.get('/api/notices',headers=owner).json()==[]  # Preview never creates a deadline/case.
    response=client.post('/api/notices/analyze',headers=owner,files={'file':('notice.pdf',payload)},data={'date_of_issue':'2026-10-15','date_of_service':'2026-10-16','window_days':15})
    assert response.status_code==200,response.text
    assert '27AABCU9603R1ZM' not in response.text
    case=response.json()['id']
    image=client.get(f'/api/notices/{case}/ocr/pages/1.png',headers=owner)
    assert image.status_code==200 and image.content.startswith(b'\x89PNG')
    assert image.headers['cache-control']=='no-store'
    _,_,stranger=create(client,messages,'outside')
    assert client.get(f'/api/notices/{case}/ocr/pages/1.png',headers=stranger).status_code==404
