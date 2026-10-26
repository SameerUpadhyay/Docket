"""Encrypted, workspace-scoped routes, durable receipts, events and expiring PII."""
import hashlib,json,os,re,secrets,time,uuid
from fastapi import HTTPException
from app import config
from app.models import database as db

def settings():
    domain=os.getenv('INBOUND_EMAIL_DOMAIN','').strip().lower()
    base=os.getenv('INBOUND_POSTMARK_ADDRESS','').strip().lower()
    mode=os.getenv('INBOUND_EMAIL_PROVIDER','hmac').strip().lower()
    agentmail=os.getenv('INBOUND_AGENTMAIL_ADDRESS','').strip().lower()
    valid_agentmail=bool(re.fullmatch(r'[a-z0-9._+\-]+@agentmail\.to',agentmail))
    valid_domain=bool(re.fullmatch(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}',domain))
    valid_domain=valid_domain and domain.rsplit('.',1)[-1] not in ('invalid','test','example','localhost')
    valid_base=bool(re.fullmatch(r'[a-z0-9]+@inbound\.postmarkapp\.com',base))
    credentials=(len(os.getenv('INBOUND_WEBHOOK_SECRET',''))>=32 if mode=='hmac' else
        bool(os.getenv('INBOUND_POSTMARK_USER')) and len(os.getenv('INBOUND_POSTMARK_PASSWORD',''))>=32 if mode=='postmark' else
        len(os.getenv('AGENTMAIL_API_KEY',''))>=32 if mode=='agentmail' else False)
    configured=(valid_agentmail if mode=='agentmail' else valid_domain or valid_base) and credentials
    return {'domain':domain if valid_domain else 'inbound.example.invalid','base':base if valid_base else '',
        'agentmail_address':agentmail if valid_agentmail else '',
        'provider':mode,'delivery_configured':bool(configured),'simulator_enabled':not config.PRODUCTION}

def validate_configuration():
    if any(os.getenv(k) for k in ('INBOUND_EMAIL_DOMAIN','INBOUND_POSTMARK_ADDRESS','INBOUND_WEBHOOK_SECRET','INBOUND_POSTMARK_PASSWORD','INBOUND_AGENTMAIL_ADDRESS','AGENTMAIL_API_KEY')):
        if not settings()['delivery_configured']: raise RuntimeError('Inbound email requires a valid receiving domain/address and strong provider credentials.')

def migrate():
    with db.connect() as tx:
        if config.DATABASE_URL: tx.execute('SELECT pg_advisory_xact_lock(482302)')
        for sql in (
            'CREATE TABLE IF NOT EXISTS email_routes (workspace TEXT PRIMARY KEY,id TEXT UNIQUE NOT NULL,address_hash TEXT UNIQUE NOT NULL,address TEXT NOT NULL,enabled INTEGER NOT NULL,confirmed_at DOUBLE PRECISION NOT NULL,created_at DOUBLE PRECISION NOT NULL)',
            'CREATE TABLE IF NOT EXISTS email_receipts (id TEXT PRIMARY KEY,workspace TEXT NOT NULL,route_id TEXT NOT NULL,fingerprint TEXT NOT NULL,status TEXT NOT NULL,notice_id TEXT NOT NULL,payload TEXT NOT NULL,created_at DOUBLE PRECISION NOT NULL,lease_until DOUBLE PRECISION NOT NULL,attempts INTEGER NOT NULL,error_code TEXT NOT NULL,simulation INTEGER NOT NULL)',
            'CREATE INDEX IF NOT EXISTS email_pending ON email_receipts(status,lease_until)',
            'CREATE INDEX IF NOT EXISTS email_receipts_workspace ON email_receipts(workspace,created_at)',
            'CREATE TABLE IF NOT EXISTS email_events (id TEXT PRIMARY KEY,workspace TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL,created_at DOUBLE PRECISION NOT NULL,expires DOUBLE PRECISION NOT NULL)',
            'CREATE INDEX IF NOT EXISTS email_events_workspace ON email_events(workspace,created_at,id)',
            'CREATE TABLE IF NOT EXISTS email_pii_vault (id TEXT PRIMARY KEY,workspace TEXT NOT NULL,notice_id TEXT NOT NULL,payload TEXT NOT NULL,expires DOUBLE PRECISION NOT NULL)',
            'CREATE TABLE IF NOT EXISTS email_verifications (workspace TEXT PRIMARY KEY,route_id TEXT NOT NULL,payload TEXT NOT NULL,expires DOUBLE PRECISION NOT NULL)',
            'CREATE TABLE IF NOT EXISTS email_agentmail_state (route_id TEXT PRIMARY KEY,watermark DOUBLE PRECISION NOT NULL,cursor TEXT NOT NULL,last_checked DOUBLE PRECISION NOT NULL,error_code TEXT NOT NULL,lease_until DOUBLE PRECISION NOT NULL)',
        ): tx.execute(sql)
        tx.execute('INSERT INTO schema_migrations VALUES (2,?) ON CONFLICT(version) DO NOTHING',(time.time(),))
        tx.execute('INSERT INTO schema_migrations VALUES (3,?) ON CONFLICT(version) DO NOTHING',(time.time(),))

def cleanup(tx):
    now=time.time()
    tx.execute('DELETE FROM email_agentmail_state WHERE route_id NOT IN (SELECT id FROM email_routes)')
    for table in ('email_events','email_pii_vault','email_verifications'): tx.execute(f'DELETE FROM {table} WHERE expires<?',(now,))
    tx.execute("UPDATE email_receipts SET payload='',status='expired',error_code='expired' WHERE created_at<? AND status IN ('pending','processing','retry')",(now-86400,))
    tx.execute('DELETE FROM email_receipts WHERE created_at<?',(now-30*86400,))

def route():
    with db.connect() as tx:
        row=tx.execute('SELECT * FROM email_routes WHERE workspace=?',(db.scope.get(),)).fetchone()
    if not row: return None
    return {'id':row['id'],'address':db.unseal(row['address']).decode(),'enabled':bool(row['enabled']),
        'confirmed_at':row['confirmed_at'],'created_at':row['created_at']}

def enable_route(rotate=False):
    current=route()
    if current and current['enabled'] and not rotate: return current
    options=settings(); token=secrets.token_hex(24)
    local='u_'+token
    address=(options['base'].replace('@','+'+local+'@',1) if options['base'] else local+'@'+options['domain'])
    if options['provider']=='agentmail' and options['delivery_configured']:
        address=options['agentmail_address']
        if rotate and current and current['address']==address:
            raise HTTPException(409,'This AgentMail inbox has a fixed address. Configure a different dedicated inbox before replacing it. You can disable receiving here at any time.')
        with db.connect() as tx:
            existing=tx.execute('SELECT workspace FROM email_routes WHERE address_hash=?',(hashlib.sha256(address.encode()).hexdigest(),)).fetchone()
        if existing and existing['workspace']!=db.scope.get():
            raise HTTPException(409,'This dedicated receiving inbox already belongs to another workspace. Configure a separate inbox for this business.')
    with db.connect() as tx:
        tx.execute('DELETE FROM email_verifications WHERE workspace=?',(db.scope.get(),))
        tx.execute("UPDATE email_receipts SET status='cancelled',payload='' WHERE workspace=? AND status IN ('pending','processing','retry')",(db.scope.get(),))
        tx.execute('INSERT INTO email_routes VALUES (?,?,?,?,1,0,?) ON CONFLICT(workspace) DO UPDATE SET id=excluded.id,address_hash=excluded.address_hash,address=excluded.address,enabled=1,confirmed_at=0,created_at=excluded.created_at',
            (db.scope.get(),uuid.uuid4().hex,hashlib.sha256(address.encode()).hexdigest(),db.seal(address),time.time()))
        db.event('','email.route.rotated' if rotate else 'email.consent.enabled',
            {'policy_version':config.POLICY_VERSION,'processing_version':'selective-email-v1','preview':not options['delivery_configured']},tx)
    return route()

def disable_route():
    with db.connect() as tx:
        tx.execute('UPDATE email_routes SET enabled=0,confirmed_at=0 WHERE workspace=?',(db.scope.get(),))
        tx.execute('DELETE FROM email_verifications WHERE workspace=?',(db.scope.get(),))
        tx.execute("UPDATE email_receipts SET status='cancelled',payload='' WHERE workspace=? AND status IN ('pending','processing','retry')",(db.scope.get(),))
        db.event('','email.consent.disabled',db=tx)

def receiving_route(address):
    with db.connect() as tx:
        row=tx.execute('SELECT r.* FROM email_routes r JOIN workspaces w ON w.id=r.workspace WHERE r.address_hash=? AND r.enabled=1',(hashlib.sha256(address.encode()).hexdigest(),)).fetchone()
    if not row: raise HTTPException(404,'Receiving address is unknown or disabled.')
    return dict(row)

def enqueue(payload,address,simulation=False):
    destination=receiving_route(address)
    content=payload.model_dump_json()
    fingerprint=hashlib.sha256(content.encode()).hexdigest()
    identifier=hashlib.sha256((destination['id']+':'+('simulation:' if simulation else '')+(payload.MessageID or fingerprint)).encode()).hexdigest()
    with db.connect() as tx:
        active=tx.execute('UPDATE email_routes SET enabled=enabled WHERE id=? AND workspace=? AND enabled=1 RETURNING id',(destination['id'],destination['workspace'])).fetchone()
        if not active: raise HTTPException(404,'Receiving address is unknown or disabled.')
        cleanup(tx)
        prior=tx.execute('SELECT fingerprint,status FROM email_receipts WHERE id=?',(identifier,)).fetchone()
        if prior:
            if prior['fingerprint']!=fingerprint: raise HTTPException(409,'Delivery ID was already used for different content.')
            return identifier,prior['status']
        pending=tx.execute("SELECT COUNT(*) AS count FROM email_receipts WHERE workspace=? AND status IN ('pending','processing','retry')",(destination['workspace'],)).fetchone()['count']
        total=tx.execute("SELECT COUNT(*) AS count FROM email_receipts WHERE status IN ('pending','processing','retry')").fetchone()['count']
        if pending>=20 or total>=200: raise HTTPException(429,'Receiving queue is full. The provider should retry later.')
        tx.execute("INSERT INTO email_receipts VALUES (?,?,?,?,'pending','',?,?,0,0,'',?) ON CONFLICT(id) DO NOTHING",
            (identifier,destination['workspace'],destination['id'],fingerprint,db.seal(content),time.time(),int(simulation)))
        result=tx.execute('SELECT fingerprint,status FROM email_receipts WHERE id=?',(identifier,)).fetchone()
        if result['fingerprint']!=fingerprint: raise HTTPException(409,'Delivery ID was already used for different content.')
    return identifier,result['status']

def publish(tx,kind,payload,workspace=None,ttl=86400):
    identifier=uuid.uuid4().hex; now=time.time()
    tx.execute('INSERT INTO email_events VALUES (?,?,?,?,?,?)',(identifier,workspace or db.scope.get(),kind,db.seal(json.dumps(payload)),now,now+ttl))
    return identifier

def events(after=''):
    with db.connect() as tx:
        cursor_time=0; cursor_id=''
        if after:
            row=tx.execute('SELECT created_at,id FROM email_events WHERE workspace=? AND id=?',(db.scope.get(),after)).fetchone()
            if row: cursor_time,cursor_id=row['created_at'],row['id']
        rows=tx.execute('SELECT id,kind,payload,created_at FROM email_events WHERE workspace=? AND expires>? AND (created_at>? OR (created_at=? AND id>?)) ORDER BY created_at,id LIMIT 50',
            (db.scope.get(),time.time(),cursor_time,cursor_time,cursor_id)).fetchall()
    return [{'id':r['id'],'event':r['kind'],'data':json.loads(db.unseal(r['payload'])),'created_at':r['created_at']} for r in rows]

def verification():
    with db.connect() as tx:
        cleanup(tx)
        row=tx.execute('SELECT v.payload,v.expires FROM email_verifications v JOIN email_routes r ON r.id=v.route_id WHERE v.workspace=? AND r.enabled=1',(db.scope.get(),)).fetchone()
    return json.loads(db.unseal(row['payload']))|{'expires_at':row['expires']} if row else None

def forget_case(tx,workspace,notice_id):
    tx.execute('DELETE FROM email_pii_vault WHERE workspace=? AND notice_id=?',(workspace,notice_id))
    tx.execute("UPDATE email_receipts SET status='deleted',payload='',notice_id='' WHERE workspace=? AND notice_id=?",(workspace,notice_id))
    # Events contain only notice IDs; purge notifications when the case is deleted.
    tx.execute('DELETE FROM email_events WHERE workspace=?',(workspace,))

def forget_workspace(tx,workspace):
    tx.execute('DELETE FROM email_agentmail_state WHERE route_id IN (SELECT id FROM email_routes WHERE workspace=?)',(workspace,))
    for table in ('email_routes','email_receipts','email_events','email_pii_vault','email_verifications'):
        tx.execute(f'DELETE FROM {table} WHERE workspace=?',(workspace,))
