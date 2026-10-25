"""Read-only operator checks. No secrets, documents or email addresses in output."""
import os,time,json
from app import config,objects
from app.models import database as db

def readiness():
    with db.connect() as tx:
        heartbeat=tx.execute("SELECT updated_at FROM worker_heartbeat WHERE name='delivery'").fetchone()
        failed=tx.execute("SELECT COUNT(*) AS count FROM reminder_jobs WHERE status='failed'").fetchone()['count']
        garbage=tx.execute('SELECT COUNT(*) AS count FROM object_deletions').fetchone()['count']
    return {'environment':config.ENVIRONMENT,'postgresql':bool(config.DATABASE_URL),'smtp_configured':config.email_configured(),'object_storage':'private-s3' if objects.configured() else 'encrypted-database','malware_scanner_configured':bool(os.getenv('CLAMAV_HOST')),'worker_age_seconds':round(time.time()-heartbeat['updated_at']) if heartbeat else None,'failed_reminders':failed,'pending_object_deletions':garbage}

if __name__=='__main__':
    config.validate_production(); db.migrate()
    print(json.dumps(readiness(),indent=2))
