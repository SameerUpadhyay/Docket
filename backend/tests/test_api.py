from io import BytesIO
from zipfile import ZipFile
from pypdf import PdfReader
from app.models import database
from app.models.schemas import NoticeState


def test_seed_and_sorted_ledger(client):
    items=client.get('/api/notices').json()
    assert len(items)==5
    assert items[-1]['severity']=='PHISHING_SCAM'
    assert items[0]['id']=='cheque-section-138'
    assert next(d for d in items if d['id']=='epfo-14b')['limitation']['effective_legal_deadline']=='2026-11-02'


def test_checklist_state_machine_and_idempotent_patch(client):
    for i in (1,2,3):
        r=client.patch(f'/api/notices/gst-asmt-10/checklist/doc-{i}',json={'is_collected':True})
        assert r.status_code==200
    assert r.json()['state']=='DRAFT_READY'
    r=client.patch('/api/notices/gst-asmt-10/checklist/doc-1',json={'is_collected':False})
    assert r.json()['state']=='DOCS_GATHERING'
    assert client.patch('/api/notices/gst-asmt-10/checklist/missing',json={'is_collected':True}).status_code==404
    assert client.patch('/api/notices/gst-quishing/checklist/doc-1',json={'is_collected':True}).status_code==409


def test_evidence_saved_and_export_contains_actual_file(client):
    r=client.post('/api/notices/gst-asmt-10/evidence/doc-1',files={'file':('reconciliation.txt',b'Evidence content','text/plain')})
    assert r.status_code==200
    assert r.json()['triage']['required_documents'][0]['attachment_name']=='reconciliation.txt'
    draft='Verified facts\n[AUTHORIZED_SIGNATORY]'
    assert client.patch('/api/notices/gst-asmt-10/draft',json={'draft_reply':draft}).status_code==200
    package=client.post('/api/notices/gst-asmt-10/export-ca-brief')
    assert package.status_code==200
    with ZipFile(BytesIO(package.content)) as z:
        assert z.read('evidence/01-doc-1.txt')==b'Evidence content'
        assert draft in z.read('professional-brief.txt').decode()
        assert 'professional-brief.pdf' in z.namelist()
        assert len(PdfReader(BytesIO(z.read('professional-brief.pdf'))).pages)>=1
    pdf=client.get('/api/notices/gst-asmt-10/reply.pdf')
    assert b'%PDF' in pdf.content[:10]
    assert 'Verified facts' in PdfReader(BytesIO(pdf.content)).pages[0].extract_text()


def test_private_upload_redaction_and_manual_dates(client):
    r=client.post('/api/notices/analyze',files={'file':('notice.txt',b'ASMT-10 CGST Section 61\nTotal demand: INR 25,000\nPAN ABCDE1234F\nAccount No: 987654321012','text/plain')},data={'date_of_issue':'2026-10-14','date_of_service':'2026-10-15','window_days':15})
    assert r.status_code==200,r.text
    data=r.json()
    assert 'ABCDE1234F' not in str(data) and '987654321012' not in str(data)
    assert data['triage']['financial_demand_inr']==25000
    assert data['limitation']['raw_expiry_date']=='2026-10-30'
    assert data['forensics']['verdict']!='VERIFIED_GOV'
    assert 'Mumbai' not in str(data['triage'])
    assert 'Apex Fasteners' not in str(data['triage'])
    assert 'Sharma' not in str(data['triage'])


def test_unknown_upload_does_not_inherit_sample_amount_or_allegation(client):
    r=client.post('/api/notices/analyze',files={'file':('notice.txt',b'Please contact our office regarding a lease.','text/plain')},data={'date_of_issue':'2026-10-24','date_of_service':'2026-10-24','window_days':7})
    assert r.status_code==200
    assert r.json()['triage']['financial_demand_inr']==0
    assert 'Unclassified' in r.json()['triage']['notice_type_title']
    assert r.json()['severity'] in ('AMBER','RED')


def test_quarantine_bypasses_ai(client,monkeypatch):
    def forbidden(*args): raise AssertionError('AI must not run for quarantined notices')
    monkeypatch.setattr('app.main.triage_with_gemini',forbidden)
    r=client.post('/api/notices/analyze',files={'file':('fraud.txt',b'GST. Pay upi://pay?pa=scammer@okicici','text/plain')},data={'date_of_issue':'2026-10-24','date_of_service':'2026-10-24','window_days':1})
    assert r.status_code==200
    assert r.json()['severity']=='PHISHING_SCAM' and r.json()['triage'] is None


def test_invalid_inputs_fail_clearly(client):
    data={'date_of_issue':'2026-10-24','date_of_service':'2026-10-20','window_days':15}
    assert client.post('/api/notices/analyze',files={'file':('x.txt',b'test')},data=data).status_code==422
    data['date_of_service']='2026-10-24'
    assert client.post('/api/notices/analyze',files={'file':('x.exe',b'payload')},data=data).status_code==415
    assert client.get('/api/privacy/gmail-filter.xml',params={'webhook_email':"bad'"}).status_code==422
    assert client.get('/api/notices/no-case/report.pdf').status_code==404


def test_closure_blocks_further_edits(client):
    d=database.get('income-tax-143')
    original=d.model_copy(deep=True)
    try:
        assert client.patch('/api/notices/income-tax-143/state',json={'state':'SUBMITTED_CLOSED'}).status_code==200
        assert client.patch('/api/notices/income-tax-143/draft',json={'draft_reply':'edit'}).status_code==409
    finally:
        database.save(original,force=True)


def test_unknown_notice_stays_flagged_after_reload(client):
    r=client.post('/api/notices/analyze',files={'file':('unknown.txt',b'Unclassified administrative query.','text/plain')},data={'date_of_issue':'2026-10-24','date_of_service':'2026-10-24','window_days':60})
    notice_id=r.json()['id']
    refreshed=next(n for n in client.get('/api/notices').json() if n['id']==notice_id)
    assert refreshed['severity']=='AMBER'


def test_executable_eml_attachment_is_quarantined(client):
    from email.message import EmailMessage
    mail=EmailMessage()
    mail['From']='sender@example.in'
    mail['To']='recipient@example.in'
    mail['Subject']='Notice'
    mail.set_content('Please see the attachment.')
    mail.add_attachment(b'not an executable',maintype='application',subtype='octet-stream',filename='notice.exe')
    r=client.post('/api/notices/analyze',files={'file':('notice.eml',mail.as_bytes(),'message/rfc822')},data={'date_of_issue':'2026-10-24','date_of_service':'2026-10-24','window_days':15})
    assert r.status_code==200
    assert r.json()['severity']=='PHISHING_SCAM'
    assert any('Executable' in flag for flag in r.json()['forensics']['scam_flags'])


def test_local_mutations_reject_external_origins(client):
    r=client.patch('/api/notices/gst-asmt-10/draft',json={'draft_reply':'injected'},headers={'Origin':'https://untrusted.example'})
    assert r.status_code==403
