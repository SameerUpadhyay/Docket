"""Verified email accounts, memory-hard passwords and revocable opaque sessions."""
import hashlib,hmac,json,re,secrets,time,uuid,threading
from fastapi import APIRouter,HTTPException,Request,Response
from pydantic import BaseModel,Field,field_validator
from app import config,mail,objects
from app.models import database as db
router=APIRouter(prefix='/api')
_password_slots=threading.BoundedSemaphore(2)

def digest(value): return hashlib.sha256(value.encode()).hexdigest()

def password_hash(password,salt=None):
    salt=salt or secrets.token_hex(16)
    if not _password_slots.acquire(timeout=2): raise HTTPException(429,'Account service is busy. Try again shortly.')
    try: hashed=hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=2**17,r=8,p=1,maxmem=256*1024*1024).hex()
    finally: _password_slots.release()
    return 'scrypt$'+salt+'$'+hashed

def password_matches(password,encoded):
    try: return hmac.compare_digest(password_hash(password,encoded.split('$')[1]),encoded)
    except (ValueError,IndexError): return False

class Credentials(BaseModel):
    email:str=Field(max_length=254)
    password:str=Field(min_length=1,max_length=128)
    @field_validator('email')
    @classmethod
    def email_valid(cls,value):
        value=value.strip().lower()
        if not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',value): raise ValueError('Enter a valid email address.')
        return value

class Registration(Credentials):
    name:str=Field(min_length=1,max_length=100)
    business:str=Field(min_length=1,max_length=160)
    consent:bool
    @field_validator('name','business')
    @classmethod
    def nonblank(cls,value):
        if not value.strip(): raise ValueError('This field cannot be blank.')
        return value.strip()

class EmailOnly(BaseModel):
    email:str=Field(max_length=254)
class Code(EmailOnly):
    code:str=Field(min_length=8,max_length=128)
class Reset(Code):
    password:str=Field(min_length=12,max_length=128)
class Password(BaseModel):
    password:str=Field(min_length=1,max_length=128)
class Profile(BaseModel):
    name:str=Field(min_length=1,max_length=100)
    business:str=Field(min_length=1,max_length=160)
    @field_validator('name','business')
    @classmethod
    def nonblank(cls,value):
        if not value.strip(): raise ValueError('This field cannot be blank.')
        return value.strip()

def throttle(key,limit=8,seconds=900):
    now=time.time(); key=digest(key)
    with db.connect() as tx:
        row=tx.execute('INSERT INTO throttles VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET count=CASE WHEN throttles.expires<? THEN 1 ELSE throttles.count+1 END,expires=CASE WHEN throttles.expires<? THEN excluded.expires ELSE throttles.expires END RETURNING count',(key,now+seconds,now,now)).fetchone()
    if row['count']>limit: raise HTTPException(429,'Too many attempts. Please try again later.',headers={'Retry-After':str(seconds)})

def limit_request(request,email=''):
    throttle('ip:'+request.client.host,100)
    if email: throttle('identity:'+email.lower().strip(),12)

def issue_code(user_id,email,purpose):
    code=f'{secrets.randbelow(10**8):08d}'
    with db.connect() as tx:
        tx.execute('DELETE FROM codes WHERE user_id=? AND purpose=?',(user_id,purpose))
        tx.execute('INSERT INTO codes VALUES (?,?,?,?,?,0)',(uuid.uuid4().hex,user_id,purpose,digest(code),time.time()+900))
    mail.send_email(email,'Docket · '+('verify your email' if purpose=='verify' else 'reset your password'),f'Your Docket {purpose} code is {code}. It expires in 15 minutes. Do not share this code.\n\nOpen {config.PUBLIC_URL} and enter the code. If you did not request this, ignore this message.')

def consume_code(email,code,purpose):
    valid=False; user_id=None
    with db.connect() as tx:
        user=tx.execute('SELECT id FROM users WHERE email=?',(email.strip().lower(),)).fetchone()
        if user:
            row=tx.execute('SELECT * FROM codes WHERE user_id=? AND purpose=?',(user['id'],purpose)).fetchone()
            if row and row['expires']>time.time():
                # Atomic attempt claim also bounds concurrent guesses across API workers.
                claim=tx.execute('UPDATE codes SET attempts=attempts+1 WHERE id=? AND attempts<6 RETURNING id',(row['id'],)).fetchone()
                if claim and hmac.compare_digest(row['hash'],digest(code)):
                    consumed=tx.execute('DELETE FROM codes WHERE id=? RETURNING user_id',(row['id'],)).fetchone()
                    if consumed: valid=True; user_id=consumed['user_id']
    if not valid: raise HTTPException(400,'The code is invalid or expired. Request a new code.')
    return user_id

def identity(token):
    if not token: raise HTTPException(401,'Sign in to your workspace.')
    with db.connect() as tx:
        row=tx.execute('SELECT users.id,users.email,users.name,sessions.expires FROM sessions JOIN users ON users.id=sessions.user_id WHERE sessions.hash=? AND users.verified=1',(digest(token),)).fetchone()
    if not row or row['expires']<=time.time(): raise HTTPException(401,'Your session has expired. Sign in again.')
    return dict(row)

def workspace(user_id,selected=None):
    with db.connect() as tx:
        rows=tx.execute('SELECT workspaces.id,workspaces.business,members.role FROM members JOIN workspaces ON workspaces.id=members.workspace WHERE members.user_id=? ORDER BY workspaces.created_at',(user_id,)).fetchall()
    selected=selected or (rows[0]['id'] if rows else '')
    current=next((dict(r) for r in rows if r['id']==selected),None)
    if not current: raise HTTPException(403,'Workspace access was revoked or does not exist.')
    return current,[dict(r) for r in rows]

def current(request):
    if not getattr(request.state,'user',None): raise HTTPException(401,'Sign in to continue.')
    return request.state.user

def owner():
    if db.role.get()!='owner': raise HTTPException(403,'Only the business owner can perform this action.')

def writable():
    if db.role.get() not in ('owner','editor'): raise HTTPException(403,'Your advisor access allows reading and review comments only.')

@router.post('/auth/register')
def register(body:Registration,request:Request):
    limit_request(request,body.email)
    if not body.consent: raise HTTPException(422,'Accept the privacy policy and terms to create an account.')
    if len(body.password)<12: raise HTTPException(422,'Use a password of at least 12 characters.')
    encoded=password_hash(body.password)
    user_id=uuid.uuid4().hex; now=time.time(); created=False
    with db.connect() as tx:
        created=tx.execute('INSERT INTO users VALUES (?,?,?,?,0,?,?,?) ON CONFLICT(email) DO NOTHING RETURNING id',(user_id,body.email,encoded,body.name.strip(),now,config.POLICY_VERSION,now)).fetchone() is not None
        if created:
            workspace_id=uuid.uuid4().hex
            tx.execute('INSERT INTO workspaces VALUES (?,?,?,?)',(workspace_id,body.business.strip(),user_id,now))
            tx.execute("INSERT INTO members VALUES (?,?,'owner')",(workspace_id,user_id))
    if created: issue_code(user_id,body.email,'verify')
    return {'message':'If eligible, a verification code has been sent. Enter it to finish creating your account.','delivery':config.MAIL_TRANSPORT if config.email_configured() else 'development-outbox'}

@router.post('/auth/resend')
def resend(body:EmailOnly,request:Request):
    limit_request(request,body.email)
    with db.connect() as tx: user=tx.execute('SELECT id,verified,email FROM users WHERE email=?',(body.email.strip().lower(),)).fetchone()
    if user and not user['verified']: issue_code(user['id'],user['email'],'verify')
    return {'message':'If an unverified account exists, a new code has been sent.'}

@router.post('/auth/verify')
def verify(body:Code,request:Request):
    limit_request(request,body.email)
    user_id=consume_code(body.email,body.code,'verify')
    with db.connect() as tx: tx.execute('UPDATE users SET verified=1 WHERE id=?',(user_id,))
    return {'message':'Email verified. You can now sign in.'}

@router.post('/auth/login')
def login(body:Credentials,request:Request,response:Response):
    limit_request(request,body.email)
    with db.connect() as tx: user=tx.execute('SELECT * FROM users WHERE email=?',(body.email,)).fetchone()
    # Equal-cost dummy work avoids a quick account-existence timing oracle.
    valid=password_matches(body.password,user['password'] if user else 'scrypt$'+'0'*32+'$'+'0'*128)
    if not user or not valid or not user['verified']: raise HTTPException(401,'Email or password is incorrect, or email verification is still required.')
    token=secrets.token_urlsafe(48); now=time.time()
    with db.connect() as tx:
        tx.execute('DELETE FROM sessions WHERE expires<?',(now,))
        tx.execute('INSERT INTO sessions VALUES (?,?,?,?,?)',(digest(token),user['id'],now+config.SESSION_SECONDS,now,request.headers.get('user-agent','Unknown device')[:160]))
    response.set_cookie('docket_session',token,max_age=config.SESSION_SECONDS,httponly=True,secure=config.PRODUCTION,samesite='strict',path='/api')
    return {'access_token':token,'token_type':'bearer','expires_in':config.SESSION_SECONDS,'user':{'id':user['id'],'email':user['email'],'name':user['name']}}

@router.post('/auth/forgot')
def forgot(body:EmailOnly,request:Request):
    limit_request(request,body.email)
    with db.connect() as tx: user=tx.execute('SELECT id,email FROM users WHERE email=? AND verified=1',(body.email.strip().lower(),)).fetchone()
    if user: issue_code(user['id'],user['email'],'reset')
    return {'message':'If a verified account exists, a reset code has been sent.'}

@router.post('/auth/reset')
def reset(body:Reset,request:Request):
    limit_request(request,body.email)
    encoded=password_hash(body.password)
    user_id=consume_code(body.email,body.code,'reset')
    with db.connect() as tx:
        tx.execute('UPDATE users SET password=? WHERE id=?',(encoded,user_id))
        tx.execute('DELETE FROM sessions WHERE user_id=?',(user_id,))
    return {'message':'Password changed and all sessions signed out.'}

@router.get('/auth/me')
def me(request:Request):
    user=current(request); selected,workspaces=workspace(user['id'],db.scope.get())
    return {'user':user,'workspace':selected,'workspaces':workspaces,'policy_version':config.POLICY_VERSION}

@router.get('/auth/sessions')
def sessions(request:Request):
    user=current(request)
    with db.connect() as tx: rows=tx.execute('SELECT created_at,expires,label FROM sessions WHERE user_id=? AND expires>? ORDER BY created_at DESC',(user['id'],time.time())).fetchall()
    return [dict(r) for r in rows]

@router.post('/auth/logout')
def logout(request:Request,response:Response):
    current(request)
    with db.connect() as tx: tx.execute('DELETE FROM sessions WHERE hash=?',(digest(request.state.token),))
    response.delete_cookie('docket_session',path='/api')
    return {'message':'Signed out.'}

@router.post('/auth/logout-all')
def logout_all(request:Request,response:Response):
    user=current(request)
    with db.connect() as tx: tx.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
    response.delete_cookie('docket_session',path='/api')
    return {'message':'All devices signed out.'}

@router.patch('/account/profile')
def profile(body:Profile,request:Request):
    user=current(request); owner()
    with db.connect() as tx:
        tx.execute('UPDATE users SET name=? WHERE id=?',(body.name.strip(),user['id']))
        tx.execute('UPDATE workspaces SET business=? WHERE id=?',(body.business.strip(),db.scope.get()))
        db.event('','profile.updated',db=tx)
    return me(request)

@router.delete('/account')
def delete_account(body:Password,request:Request,response:Response):
    user=current(request)
    throttle('delete:'+user['id'],6)
    with db.connect() as tx:
        row=tx.execute('SELECT password FROM users WHERE id=?',(user['id'],)).fetchone()
        if not row or not password_matches(body.password,row['password']): raise HTTPException(401,'Password is incorrect.')
        owned=tx.execute('SELECT id FROM workspaces WHERE owner_id=?',(user['id'],)).fetchall()
        for workspace_row in owned:
            for file in tx.execute('SELECT content FROM files_v2 WHERE workspace=?',(workspace_row['id'],)).fetchall(): objects.queue_delete(tx,file['content'])
            for table in ('cases_v2','files_v2','history','invitations','reminder_jobs','preferences','ocr_preferences','members'):
                tx.execute(f'DELETE FROM {table} WHERE workspace=?',(workspace_row['id'],))
            tx.execute('DELETE FROM workspaces WHERE id=?',(workspace_row['id'],))
        tx.execute('DELETE FROM members WHERE user_id=?',(user['id'],))
        tx.execute('DELETE FROM reminder_jobs WHERE user_id=?',(user['id'],))
        for table in ('sessions','codes'): tx.execute(f'DELETE FROM {table} WHERE user_id=?',(user['id'],))
        tx.execute('DELETE FROM users WHERE id=?',(user['id'],))
    response.delete_cookie('docket_session',path='/api')
    return {'message':'Your account, owned workspaces and their live records were deleted. Expiring encrypted backups follow the published retention schedule.'}
