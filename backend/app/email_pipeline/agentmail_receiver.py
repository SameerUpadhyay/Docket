"""Read a dedicated AgentMail inbox over outbound HTTPS; never access Gmail.

The inbox-scoped read-only key cannot send, delete or modify provider mail.
Original MIME follows the existing encrypted queue and local screening pipeline.
"""
import base64,hashlib,json,os,time
from datetime import datetime,timezone
from urllib.parse import quote,urlsplit
import httpx
from fastapi import HTTPException
from . import store
from .schemas_email import InboundEmail,MAX_MESSAGE_BYTES
from app.models import database as db

API='https://api.agentmail.to/v0'


def _get(path,params=None):
    try:
        with httpx.Client(timeout=20,follow_redirects=False,trust_env=False) as client:
            response=client.get(API+path,params=params,headers={'Authorization':'Bearer '+os.environ['AGENTMAIL_API_KEY']})
            if response.status_code in (401,403): raise HTTPException(503,'agentmail-key-denied')
            if response.status_code==429: raise HTTPException(503,'agentmail-rate-limited')
            if response.status_code!=200: raise HTTPException(503,'agentmail-unavailable')
            if len(response.content)>2*1024*1024: raise HTTPException(503,'agentmail-response-too-large')
            return response.json()
    except (httpx.HTTPError,ValueError): raise HTTPException(503,'agentmail-unavailable') from None


def inbox_path():
    return '/inboxes/'+quote(os.getenv('AGENTMAIL_INBOX_ID') or store.settings()['agentmail_address'],safe='')


def verify_inbox():
    result=_get(inbox_path())
    address=result.get('email') or result.get('inbox_id')
    if address!=store.settings()['agentmail_address'] or result.get('status')=='paused':
        raise HTTPException(503,'agentmail-inbox-mismatch')
    return True


def _download(url):
    parsed=urlsplit(url)
    # AgentMail returns its own CDN or signed CloudFront URLs. Never send its API
    # credential to a download host or follow redirects to another destination.
    allowed_host=parsed.hostname=='cdn.agentmail.to' or bool(parsed.hostname and parsed.hostname.endswith('.cloudfront.net'))
    if parsed.scheme!='https' or not allowed_host or parsed.port not in (None,443) or parsed.username or parsed.password:
        raise HTTPException(503,'agentmail-download-host-rejected')
    try:
        with httpx.Client(timeout=20,follow_redirects=False,trust_env=False) as client:
            with client.stream('GET',url) as response:
                if response.status_code!=200: raise HTTPException(503,'agentmail-download-unavailable')
                chunks=[]; size=0
                for chunk in response.iter_bytes(65536):
                    size+=len(chunk)
                    if size>MAX_MESSAGE_BYTES: raise HTTPException(413,'agentmail-message-too-large')
                    chunks.append(chunk)
                if not size: raise HTTPException(422,'agentmail-empty-message')
                return b''.join(chunks)
    except httpx.HTTPError: raise HTTPException(503,'agentmail-download-unavailable') from None


def _created(message):
    # Provider creation time, rather than the sender-controlled Date header.
    value=message.get('created_at','')
    try: return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
    except (ValueError,TypeError,AttributeError): raise HTTPException(503,'agentmail-missing-created-time') from None


def _accept(route,message):
    created=_created(message)
    if created<max(route['created_at'],time.time()-30*86400): return 0
    provider_id=message.get('message_id','')
    if not isinstance(provider_id,str) or not 0<len(provider_id)<=480: raise HTTPException(503,'agentmail-invalid-message-id')
    message_id='agentmail:'+provider_id
    identifier=hashlib.sha256((route['id']+':'+message_id).encode()).hexdigest()
    with db.connect() as tx:
        if tx.execute('SELECT id FROM email_receipts WHERE id=?',(identifier,)).fetchone(): return 0
    path=inbox_path()+'/messages/'+quote(provider_id,safe='')+'/raw'
    raw_info=_get(path)
    try:
        size=raw_info.get('size')
        if not isinstance(size,int) or size<1: raise HTTPException(422,'agentmail-empty-message')
        if size>MAX_MESSAGE_BYTES: raise HTTPException(413,'agentmail-message-too-large')
        raw=_download(raw_info.get('download_url',''))
        payload=InboundEmail(OriginalRecipient=store.settings()['agentmail_address'],MessageID=message_id,RawEmail=base64.b64encode(raw).decode())
    except HTTPException as error:
        if error.status_code>=500: raise
        # Record a content-free rejection so an oversized/empty item cannot
        # starve newer deliveries or get fetched forever on every scan.
        payload=InboundEmail(OriginalRecipient=store.settings()['agentmail_address'],MessageID=message_id)
        receipt,_=store.enqueue(payload,payload.OriginalRecipient)
        with db.connect() as tx:
            tx.execute("UPDATE email_receipts SET status='rejected',payload='',error_code=? WHERE id=? AND status='pending'",(error.detail,receipt))
        return 1
    store.enqueue(payload,payload.OriginalRecipient)
    return 1


def poll_once():
    options=store.settings()
    if options['provider']!='agentmail' or not options['delivery_configured']: return 0
    try: route=store.receiving_route(options['agentmail_address'])
    except HTTPException: return 0
    now=time.time(); lease=now+900
    with db.connect() as tx:
        tx.execute("INSERT INTO email_agentmail_state VALUES (?,?,?,0,'',0) ON CONFLICT(route_id) DO NOTHING",(route['id'],route['created_at'],''))
        state=tx.execute('UPDATE email_agentmail_state SET lease_until=? WHERE route_id=? AND lease_until<=? AND last_checked<=? RETURNING *',(lease,route['id'],now,now-15)).fetchone()
    if not state: return 0
    cursor={}
    accepted=0; error=''
    try:
        cursor=json.loads(db.unseal(state['cursor'])) if state['cursor'] else {}
        verify_inbox()
        # Inspect the newest page each time; continue older pages separately so
        # backdated Date headers and a backlog cannot permanently hide mail.
        pages=[{}]
        if cursor: pages.append(cursor)
        for scan in pages:
            for _ in range(1 if not scan else 3):
                params={'limit':100,'include_spam':'true','include_unauthenticated':'true'}
                if scan.get('token'): params['page_token']=scan['token']
                result=_get(inbox_path()+'/messages',params)
                messages=result.get('messages')
                if not isinstance(messages,list) or len(messages)>100: raise HTTPException(503,'agentmail-invalid-page')
                for message in messages: accepted+=_accept(route,message)
                token=result.get('next_page_token')
                if not token:
                    if scan: cursor={}
                    break
                scan={'token':token}
                cursor=scan
    except HTTPException as exception:
        error=exception.detail if exception.status_code>=500 and isinstance(exception.detail,str) and exception.detail.startswith('agentmail-') else 'agentmail-receiving-paused' if exception.status_code==404 else 'agentmail-queue-full' if exception.status_code==429 else 'agentmail-retry-needed'
    except Exception:
        error='agentmail-retry-needed'
    finally:
        with db.connect() as tx:
            tx.execute('UPDATE email_agentmail_state SET cursor=?,last_checked=?,error_code=?,lease_until=0 WHERE route_id=? AND lease_until=?',
                (db.seal(json.dumps(cursor)) if cursor else '',time.time(),error,route['id'],lease))
    return accepted
