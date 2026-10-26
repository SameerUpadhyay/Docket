"""Versioned, tenant-scoped persistence; authenticated encryption for case content.

Legacy prototype tables are deliberately not imported into any user's workspace.
SQLite is for local development; the same schema/queries run on PostgreSQL.
"""
import json,os,sqlite3,time,uuid,hashlib,base64
from pathlib import Path
from contextlib import contextmanager
from contextvars import ContextVar
from cryptography.fernet import Fernet
from app import config,objects
from app.models.schemas import CompleteNoticeDossier

scope=ContextVar('workspace',default='demo')
actor=ContextVar('actor',default='demo')
role=ContextVar('role',default='owner')
_cipher=None

class Connection:
    def __init__(self,raw,postgres): self.raw,self.postgres=raw,postgres
    def execute(self,sql,params=()): return self.raw.execute(sql.replace('?','%s') if self.postgres else sql,params)

@contextmanager
def connect():
    if config.DATABASE_URL:
        import psycopg
        from psycopg.rows import dict_row
        raw=psycopg.connect(config.DATABASE_URL,row_factory=dict_row)
    else:
        Path(config.DATABASE_PATH).parent.mkdir(parents=True,exist_ok=True)
        try:
            fd=os.open(config.DATABASE_PATH,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); os.close(fd)
        except FileExistsError: pass
        raw=sqlite3.connect(config.DATABASE_PATH,timeout=30)
        raw.row_factory=sqlite3.Row
        raw.execute('PRAGMA journal_mode=WAL')
        raw.execute('PRAGMA foreign_keys=ON')
        raw.execute('PRAGMA secure_delete=ON')
    try:
        yield Connection(raw,bool(config.DATABASE_URL))
        raw.commit()
    except Exception:
        raw.rollback(); raise
    finally: raw.close()

def cipher():
    global _cipher
    if _cipher is None:
        key=os.getenv('DATA_ENCRYPTION_KEY')
        if not key and os.getenv('DATA_ENCRYPTION_SECRET'):
            key=base64.urlsafe_b64encode(hashlib.sha256(os.environ['DATA_ENCRYPTION_SECRET'].encode()).digest())
        if not key:
            if config.PRODUCTION: raise RuntimeError('Missing DATA_ENCRYPTION_KEY')
            key_file=Path(config.DATABASE_PATH).with_suffix('.key')
            try:
                fd=os.open(key_file,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'wb') as stream: stream.write(Fernet.generate_key())
            except FileExistsError: pass
            key=key_file.read_bytes()
        _cipher=Fernet(key)
    return _cipher

def seal(value): return cipher().encrypt(value.encode() if isinstance(value,str) else value).decode()
def unseal(value): return cipher().decrypt(value.encode())

def migrate():
    statements=[
      'CREATE TABLE IF NOT EXISTS legacy_archive (id TEXT PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL)',
      'CREATE TABLE IF NOT EXISTS object_deletions (key TEXT PRIMARY KEY,attempts INTEGER NOT NULL)',
      'CREATE TABLE IF NOT EXISTS worker_heartbeat (name TEXT PRIMARY KEY,updated_at DOUBLE PRECISION NOT NULL)',
      'CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at DOUBLE PRECISION NOT NULL)',
      'CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL,name TEXT NOT NULL,verified INTEGER NOT NULL,created_at DOUBLE PRECISION NOT NULL,policy_version TEXT NOT NULL,consented_at DOUBLE PRECISION NOT NULL)',
      'CREATE TABLE IF NOT EXISTS workspaces (id TEXT PRIMARY KEY,business TEXT NOT NULL,owner_id TEXT NOT NULL,created_at DOUBLE PRECISION NOT NULL)',
      'CREATE TABLE IF NOT EXISTS members (workspace TEXT NOT NULL,user_id TEXT NOT NULL,role TEXT NOT NULL,PRIMARY KEY(workspace,user_id))',
      'CREATE TABLE IF NOT EXISTS sessions (hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires DOUBLE PRECISION NOT NULL,created_at DOUBLE PRECISION NOT NULL,label TEXT NOT NULL)',
      'CREATE TABLE IF NOT EXISTS codes (id TEXT PRIMARY KEY,user_id TEXT NOT NULL,purpose TEXT NOT NULL,hash TEXT NOT NULL,expires DOUBLE PRECISION NOT NULL,attempts INTEGER NOT NULL)',
      'CREATE TABLE IF NOT EXISTS throttles (key TEXT PRIMARY KEY,count INTEGER NOT NULL,expires DOUBLE PRECISION NOT NULL)',
      'CREATE TABLE IF NOT EXISTS cases_v2 (workspace TEXT NOT NULL,id TEXT NOT NULL,dossier TEXT NOT NULL,updated_at DOUBLE PRECISION NOT NULL,PRIMARY KEY(workspace,id))',
      'CREATE TABLE IF NOT EXISTS files_v2 (workspace TEXT NOT NULL,notice_id TEXT NOT NULL,doc_id TEXT NOT NULL,name TEXT NOT NULL,content TEXT NOT NULL,PRIMARY KEY(workspace,notice_id,doc_id))',
      'CREATE TABLE IF NOT EXISTS history (id TEXT PRIMARY KEY,workspace TEXT NOT NULL,notice_id TEXT NOT NULL,actor TEXT NOT NULL,event TEXT NOT NULL,created_at DOUBLE PRECISION NOT NULL,details TEXT NOT NULL)',
      'CREATE TABLE IF NOT EXISTS invitations (hash TEXT PRIMARY KEY,workspace TEXT NOT NULL,email TEXT NOT NULL,role TEXT NOT NULL,expires DOUBLE PRECISION NOT NULL)',
      'CREATE TABLE IF NOT EXISTS reminder_jobs (id TEXT PRIMARY KEY,workspace TEXT NOT NULL,notice_id TEXT NOT NULL,user_id TEXT NOT NULL,due DOUBLE PRECISION NOT NULL,status TEXT NOT NULL,attempts INTEGER NOT NULL,next_attempt DOUBLE PRECISION NOT NULL,lease_until DOUBLE PRECISION NOT NULL)',
      'CREATE TABLE IF NOT EXISTS ocr_preferences (workspace TEXT PRIMARY KEY,cloud_ocr INTEGER NOT NULL)',
      'CREATE TABLE IF NOT EXISTS preferences (workspace TEXT PRIMARY KEY,email_reminders INTEGER NOT NULL,external_ai INTEGER NOT NULL,retain_original INTEGER NOT NULL)',
      'CREATE INDEX IF NOT EXISTS jobs_pending ON reminder_jobs(status,next_attempt)',
      'CREATE INDEX IF NOT EXISTS history_case ON history(workspace,notice_id,created_at)',
    ]
    legacy_migrated=False
    with connect() as db:
        if config.DATABASE_URL: db.execute('SELECT pg_advisory_xact_lock(482301)')
        for sql in statements: db.execute(sql)
        db.execute('INSERT INTO schema_migrations VALUES (1,?) ON CONFLICT(version) DO NOTHING',(time.time(),))
        if not config.DATABASE_URL:
            legacy={row['name'] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('notices','evidence')").fetchall()}
            if 'notices' in legacy:
                for row in db.execute('SELECT id,dossier FROM notices').fetchall():
                    db.execute('INSERT INTO legacy_archive VALUES (?,?,?) ON CONFLICT(id) DO NOTHING',('notice:'+row['id'],'notice',seal(row['dossier'])))
                db.execute('DROP TABLE notices'); legacy_migrated=True
            if 'evidence' in legacy:
                for row in db.execute('SELECT notice_id,doc_id,name,content FROM evidence').fetchall():
                    record=dict(row); record['content']=base64.b64encode(record['content']).decode()
                    identifier=hashlib.sha256((row['notice_id']+':'+row['doc_id']).encode()).hexdigest()
                    db.execute('INSERT INTO legacy_archive VALUES (?,?,?) ON CONFLICT(id) DO NOTHING',('evidence:'+identifier,'evidence',seal(json.dumps(record))))
                db.execute('DROP TABLE evidence'); legacy_migrated=True
    cipher()
    if legacy_migrated:
        with connect() as db: db.execute('PRAGMA wal_checkpoint(TRUNCATE)')

def event(notice_id,name,details=None,db=None):
    values=(uuid.uuid4().hex,scope.get(),notice_id,actor.get(),name,time.time(),seal(json.dumps(details or {})))
    sql='INSERT INTO history VALUES (?,?,?,?,?,?,?)'
    if db: db.execute(sql,values)
    else:
        with connect() as tx: tx.execute(sql,values)

def history(notice_id):
    with connect() as db:
        rows=db.execute('SELECT id,actor,event,created_at,details FROM history WHERE workspace=? AND notice_id=? ORDER BY created_at DESC',(scope.get(),notice_id)).fetchall()
    return [dict(r)|{'details':json.loads(unseal(r['details']))} for r in rows]

def save(dossier,event_name='case.updated',force=False):
    from fastapi import HTTPException
    with connect() as db:
        prior=db.execute('SELECT dossier FROM cases_v2 WHERE workspace=? AND id=?',(scope.get(),dossier.id)).fetchone()
        details={'state':dossier.state.value}
        if prior:
            previous=CompleteNoticeDossier.model_validate_json(unseal(prior['dossier']))
            if not force and dossier.revision!=previous.revision: raise HTTPException(409,'Case changed concurrently. Refresh it before continuing.')
            if previous.triage!=dossier.triage:
                dossier.professional_review='PENDING'; dossier.submission_receipt=None; dossier.submitted_at=None
            if previous.draft_reply!=dossier.draft_reply:
                dossier.professional_review='PENDING'; dossier.submission_receipt=None; dossier.submitted_at=None
                event_name='draft.saved'; details['previous_draft']=previous.draft_reply or (previous.triage.draft_reply_template if previous.triage else '')
            dossier.revision=previous.revision+1
            updated=db.execute('UPDATE cases_v2 SET dossier=?,updated_at=? WHERE workspace=? AND id=? AND dossier=? RETURNING id',(seal(dossier.model_dump_json()),time.time(),scope.get(),dossier.id,prior['dossier'])).fetchone()
            if not updated: raise HTTPException(409,'Case changed concurrently. Refresh it before continuing.')
        else:
            dossier.revision=1
            db.execute('INSERT INTO cases_v2 VALUES (?,?,?,?)',(scope.get(),dossier.id,seal(dossier.model_dump_json()),time.time()))
        event(dossier.id,event_name,details,db)
        if dossier.state.value=='SUBMITTED_CLOSED':
            db.execute("UPDATE reminder_jobs SET status='cancelled' WHERE workspace=? AND notice_id=? AND status<>'sent'",(scope.get(),dossier.id))
    return dossier

def get(notice_id):
    with connect() as db: row=db.execute('SELECT dossier FROM cases_v2 WHERE workspace=? AND id=?',(scope.get(),notice_id)).fetchone()
    return CompleteNoticeDossier.model_validate_json(unseal(row['dossier'])) if row else None

def all_notices():
    with connect() as db: rows=db.execute('SELECT dossier FROM cases_v2 WHERE workspace=?',(scope.get(),)).fetchall()
    return [CompleteNoticeDossier.model_validate_json(unseal(r['dossier'])) for r in rows]

def save_evidence(notice_id,doc_id,name,content):
    encrypted=seal(content)
    reference=objects.put(encrypted,scope.get()) if objects.configured() else encrypted
    try:
        with connect() as db:
            prior=db.execute('SELECT content FROM files_v2 WHERE workspace=? AND notice_id=? AND doc_id=?',(scope.get(),notice_id,doc_id)).fetchone()
            db.execute('INSERT INTO files_v2 VALUES (?,?,?,?,?) ON CONFLICT(workspace,notice_id,doc_id) DO UPDATE SET name=excluded.name,content=excluded.content',(scope.get(),notice_id,doc_id,name,reference))
            if prior: objects.queue_delete(db,prior['content'])
            event(notice_id,'file.saved',{'document':doc_id,'name':name},db)
    except Exception:
        if reference.startswith('s3:'):
            with connect() as tx: objects.queue_delete(tx,reference)
        raise

def evidence(notice_id):
    with connect() as db: rows=db.execute('SELECT doc_id,name,content FROM files_v2 WHERE workspace=? AND notice_id=?',(scope.get(),notice_id)).fetchall()
    return [(r['doc_id'],r['name'],unseal(objects.get(r['content']) if r['content'].startswith('s3:') else r['content'])) for r in rows]

def delete_case(notice_id):
    with connect() as db:
        from app.email_pipeline.store import forget_case
        forget_case(db,scope.get(),notice_id)
        for row in db.execute('SELECT content FROM files_v2 WHERE workspace=? AND notice_id=?',(scope.get(),notice_id)).fetchall(): objects.queue_delete(db,row['content'])
        for table in ('files_v2','history','reminder_jobs'):
            db.execute(f'DELETE FROM {table} WHERE workspace=? AND notice_id=?',(scope.get(),notice_id))
        db.execute('DELETE FROM cases_v2 WHERE workspace=? AND id=?',(scope.get(),notice_id))

def preferences():
    with connect() as db: row=db.execute('SELECT email_reminders,external_ai,retain_original FROM preferences WHERE workspace=?',(scope.get(),)).fetchone()
    with connect() as db: ocr=db.execute('SELECT cloud_ocr FROM ocr_preferences WHERE workspace=?',(scope.get(),)).fetchone()
    return (dict(row) if row else {'email_reminders':0,'external_ai':0,'retain_original':0})|{'cloud_ocr':ocr['cloud_ocr'] if ocr else 0}


def evidence_document(notice_id,doc_id):
    with connect() as tx: row=tx.execute('SELECT name,content FROM files_v2 WHERE workspace=? AND notice_id=? AND doc_id=?',(scope.get(),notice_id,doc_id)).fetchone()
    if not row: return None
    content=objects.get(row['content']) if row['content'].startswith('s3:') else row['content']
    return row['name'],unseal(content)
