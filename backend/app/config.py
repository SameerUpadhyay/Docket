"""Environment configuration. Production starts only with explicit service settings."""
import os
from pathlib import Path
DATA_DIR=Path(__file__).parent/'data'
DATABASE_PATH=os.getenv('DATABASE_PATH',str(DATA_DIR/'docket.sqlite3'))
DATABASE_URL=os.getenv('DATABASE_URL','')
if not DATABASE_URL and os.getenv('DB_HOST'):
    from urllib.parse import quote,urlencode
    credentials=quote(os.environ['DB_USER'],safe='')+':'+quote(os.environ['DB_PASSWORD'],safe='')
    options={'sslmode':'verify-full','sslrootcert':os.getenv('DATABASE_SSLROOTCERT','/service/rds-ca.pem')}
    DATABASE_URL=f"postgresql://{credentials}@{os.environ['DB_HOST']}:5432/{os.getenv('DB_NAME','docket')}?{urlencode(options)}"
ENVIRONMENT=os.getenv('DOCKET_ENV','development')
PRODUCTION=ENVIRONMENT=='production'
# Only tests / an explicitly isolated demo server may bypass authentication.
DEMO_MODE=os.getenv('DOCKET_DEMO_MODE','0')=='1' and not PRODUCTION
ALLOWED_ORIGINS=tuple(x.strip() for x in os.getenv('ALLOWED_ORIGINS','http://127.0.0.1:3000,http://localhost:3000').split(',') if x.strip())
PUBLIC_URL=os.getenv('PUBLIC_URL','http://127.0.0.1:3000').rstrip('/')
GEMINI_API_KEY=os.getenv('GEMINI_API_KEY','')
GEMINI_MODEL=os.getenv('GEMINI_MODEL','gemini-2.5-flash')
MAX_UPLOAD_BYTES=10*1024*1024
MAIL_TRANSPORT=os.getenv('MAIL_TRANSPORT','smtp')
SMTP_HOST=os.getenv('SMTP_HOST','')
SES_CONFIGURATION_SET=os.getenv('SES_CONFIGURATION_SET','')
SMTP_PORT=int(os.getenv('SMTP_PORT','587'))
SMTP_USER=os.getenv('SMTP_USER','')
SMTP_PASSWORD=os.getenv('SMTP_PASSWORD','')
MAIL_FROM=os.getenv('MAIL_FROM','Docket <no-reply@localhost>')
SUPPORT_EMAIL=os.getenv('SUPPORT_EMAIL','')
SESSION_SECONDS=12*3600
POLICY_VERSION='2026-10-25'

def validate_production():
    if not PRODUCTION: return
    missing=[]
    if not DATABASE_URL.startswith(('postgresql://','postgres://')): missing.append('PostgreSQL DATABASE_URL')
    if not (os.getenv('DATA_ENCRYPTION_KEY') or os.getenv('DATA_ENCRYPTION_SECRET')): missing.append('DATA_ENCRYPTION_KEY')
    if MAIL_TRANSPORT not in ('smtp','ses'): missing.append('MAIL_TRANSPORT smtp or ses')
    if (MAIL_TRANSPORT=='smtp' and not SMTP_HOST) or not SUPPORT_EMAIL or 'localhost' in MAIL_FROM: missing.append('mail transport, MAIL_FROM and SUPPORT_EMAIL')
    if not PUBLIC_URL.startswith('https://'): missing.append('HTTPS PUBLIC_URL')
    if not ALLOWED_ORIGINS or any(not x.startswith('https://') for x in ALLOWED_ORIGINS): missing.append('HTTPS ALLOWED_ORIGINS')
    if missing: raise RuntimeError('Production configuration missing: '+', '.join(missing))

def email_configured(): return MAIL_TRANSPORT=='ses' or bool(SMTP_HOST)
