"""Dedicated-inbox isolation, recovery, raw MIME and outbound-download controls."""
import time,uuid
from email.message import EmailMessage
from email import policy
import httpx,pytest
from fastapi import HTTPException
from app.models import database as db
from app.email_pipeline import store,processor,agentmail_receiver as receiver
from test_email_privacy_pipeline import intake,PREFIX,cases
from test_accounts import create


def configure(monkeypatch):
    monkeypatch.setenv('INBOUND_EMAIL_PROVIDER','agentmail')
    monkeypatch.setenv('INBOUND_AGENTMAIL_ADDRESS','docket-test-'+uuid.uuid4().hex+'@agentmail.to')
    monkeypatch.setenv('AGENTMAIL_API_KEY','test-only-'+('a'*48))


def fake_provider(monkeypatch,messages):
    raw=EmailMessage(policy=policy.SMTP)
    raw['From']='notice@cbic.gov.in'; raw['To']='owner@gmail.com'; raw['Subject']='Form GST ASMT-10'
    raw.set_content('Form GST ASMT-10 CGST Section 61. PAN ABCDE1234F. Demand INR 25000.')
    content=raw.as_bytes(); calls=[]
    def get(path,params=None):
        calls.append((path,params))
        if path.endswith('/raw'): return {'size':len(content),'download_url':'https://example.cloudfront.net/raw?signature=test'}
        if path.endswith('/messages'): return {'messages':messages}
        return {'email':store.settings()['agentmail_address']}
    monkeypatch.setattr(receiver,'_get',get)
    monkeypatch.setattr(receiver,'_download',lambda url:content)
    return calls


def again():
    with db.connect() as tx: tx.execute('UPDATE email_agentmail_state SET last_checked=0')


def test_dedicated_inbox_raw_mime_recovery_and_deduplication(intake,monkeypatch):
    client,_,owner,_,_=intake; configure(monkeypatch)
    route=client.post(PREFIX+'/routing/rotate',headers=owner,json={'consent':True}).json()
    assert route['address']==store.settings()['agentmail_address']
    message={'message_id':'<provider-id>','created_at':time.strftime('%Y-%m-%dT%H:%M:%S',time.gmtime(time.time()+1))+'Z'}
    calls=fake_provider(monkeypatch,[message])
    assert receiver.poll_once()==1
    assert processor.process_next() is True
    item=cases(client,owner)[0]
    assert item['email_intake'] and 'ABCDE1234F' not in item['redacted_ocr_excerpt']
    assert receiver.poll_once()==0 # persisted check interval
    again(); assert receiver.poll_once()==0
    assert len(cases(client,owner))==1
    assert len([p for p,_ in calls if p.endswith('/raw')])==1
    settings=client.get(PREFIX+'/settings',headers=owner).json()
    assert settings['connection']['last_checked']>0 and settings['connection']['error_code']==''
    assert settings['fixed_receiving_address'] is True
    assert client.post(PREFIX+'/routing/rotate',headers=owner,json={'consent':True}).status_code==409
    assert client.post(PREFIX+'/routing/confirm',headers=owner,json={'consent':True}).status_code==200
    assert client.get(PREFIX+'/gmail-filter.xml',headers=owner).status_code==200
    assert client.post(PREFIX+'/inbound-webhook',json={}).status_code==503 # no public bypass


def test_dedicated_inbox_cannot_be_shared_across_workspaces(intake,monkeypatch):
    client,messages,owner,_,_=intake; configure(monkeypatch)
    assert client.post(PREFIX+'/routing/rotate',headers=owner,json={'consent':True}).status_code==200
    _,_,other=create(client,messages,'agentmail-other')
    assert client.post(PREFIX+'/routing',headers=other,json={'consent':True}).status_code==409


def test_revocation_during_raw_download_cannot_create_case(intake,monkeypatch):
    client,_,owner,_,_=intake; configure(monkeypatch)
    client.post(PREFIX+'/routing/rotate',headers=owner,json={'consent':True})
    fake_provider(monkeypatch,[{'message_id':'id','created_at':'2099-01-01T00:00:00Z'}])
    original=receiver._download
    def revoke(url):
        assert client.delete(PREFIX+'/routing',headers=owner).status_code==200
        return original(url)
    monkeypatch.setattr(receiver,'_download',revoke)
    assert receiver.poll_once()==0
    assert cases(client,owner)==[]
    assert receiver.poll_once()==0


def test_oversized_item_is_rejected_without_blocking_later_delivery(intake,monkeypatch):
    client,_,owner,_,_=intake; configure(monkeypatch)
    client.post(PREFIX+'/routing/rotate',headers=owner,json={'consent':True})
    fake_provider(monkeypatch,[{'message_id':'too-big','created_at':'2099-01-01T00:00:00Z'}])
    original=receiver._get
    monkeypatch.setattr(receiver,'_get',lambda path,params=None:{'size':receiver.MAX_MESSAGE_BYTES+1} if path.endswith('/raw') else original(path,params))
    assert receiver.poll_once()==1
    receipts=client.get(PREFIX+'/receipts',headers=owner).json()
    assert receipts[0]['status']=='rejected' and receipts[0]['error_code']=='agentmail-message-too-large'
    again(); assert receiver.poll_once()==0
    assert cases(client,owner)==[]


@pytest.mark.parametrize('url',['http://example.cloudfront.net/raw','https://127.0.0.1/raw','https://example.cloudfront.net.evil.com/raw','https://cdn.agentmail.to.evil.com/raw','https://user:secret@example.cloudfront.net/raw','https://example.cloudfront.net:8080/raw'])
def test_raw_download_rejects_untrusted_targets(url):
    with pytest.raises(HTTPException): receiver._download(url)


@pytest.mark.parametrize('host',['example.cloudfront.net','cdn.agentmail.to'])
def test_download_is_bounded_and_never_forwards_api_key(monkeypatch,host):
    original=httpx.Client
    def handle(request):
        assert 'authorization' not in request.headers
        return httpx.Response(200,content=b'x'*(receiver.MAX_MESSAGE_BYTES+1))
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(handle),**kw))
    with pytest.raises(HTTPException) as error: receiver._download('https://'+host+'/raw')
    assert error.value.status_code==413


def test_old_provider_creation_time_is_not_reimported(intake,monkeypatch):
    client,_,owner,_,_=intake; configure(monkeypatch)
    client.post(PREFIX+'/routing/rotate',headers=owner,json={'consent':True})
    calls=fake_provider(monkeypatch,[{'message_id':'old','created_at':'2020-01-01T00:00:00Z','timestamp':'2099-01-01T00:00:00Z'}])
    assert receiver.poll_once()==0
    assert not any(path.endswith('/raw') for path,_ in calls)
    assert cases(client,owner)==[]
