"""Persistent email reminders. Run as a separate supervised service.

Leases and atomic claims support multiple workers. SMTP is at-least-once: a crash
between sending and committing may deliver twice. Case content is never emailed.
"""
import logging,time,os
from app import config,mail,objects
from app.models import database as db
logger=logging.getLogger('docket.delivery')

def tick():
    if objects.configured(): objects.collect()
    now=time.time()
    with db.connect() as tx:
        rows=tx.execute("SELECT id FROM reminder_jobs WHERE ((status='pending' AND next_attempt<=?) OR (status='sending' AND lease_until<?)) AND attempts<5 ORDER BY due LIMIT 25",(now,now)).fetchall()
    for row in rows:
        with db.connect() as tx:
            job=tx.execute("UPDATE reminder_jobs SET status='sending',attempts=attempts+1,lease_until=? WHERE id=? AND ((status='pending' AND next_attempt<=?) OR (status='sending' AND lease_until<?)) RETURNING *",(now+180,row['id'],now,now)).fetchone()
        if not job: continue
        token=db.scope.set(job['workspace'])
        try:
            with db.connect() as tx:
                recipient=tx.execute('SELECT email FROM users WHERE id=? AND verified=1',(job['user_id'],)).fetchone()
            d=db.get(job['notice_id'])
            if not recipient or not d or d.is_demo or d.state.value=='SUBMITTED_CLOSED' or not db.preferences()['email_reminders']:
                status='cancelled'
            elif time.time()>job['due']+24*3600:
                status='expired'
            else:
                mail.send_email(recipient['email'],'Docket · a case deadline needs attention',f'A confirmed planning deadline is approaching. Open your secure workspace to review the case and verify the applicable deadline.\n{config.PUBLIC_URL}\n\nNo document or response has been filed. Delivery of reminders is not guaranteed.')
                status='sent'
            with db.connect() as tx: tx.execute('UPDATE reminder_jobs SET status=?,lease_until=0 WHERE id=?',(status,job['id']))
        except Exception:
            logger.error('reminder_delivery_failed attempt=%s',job['attempts'])
            with db.connect() as tx: tx.execute('UPDATE reminder_jobs SET status=?,next_attempt=?,lease_until=0 WHERE id=?',('failed' if job['attempts']>=5 else 'pending',time.time()+min(3600,60*2**job['attempts']),job['id']))
        finally: db.scope.reset(token)
    with db.connect() as tx:
        tx.execute("INSERT INTO worker_heartbeat VALUES ('delivery',?) ON CONFLICT(name) DO UPDATE SET updated_at=excluded.updated_at",(time.time(),))
        tx.execute('DELETE FROM throttles WHERE expires<?',(now-3600,))
        tx.execute('DELETE FROM codes WHERE expires<?',(now-3600,))
        tx.execute('DELETE FROM sessions WHERE expires<?',(now,))
        tx.execute('DELETE FROM invitations WHERE expires<?',(now,))
    if os.getenv('METRICS_NAMESPACE'):
        try:
            import boto3
            with db.connect() as tx: failed=tx.execute("SELECT COUNT(*) AS count FROM reminder_jobs WHERE status='failed'").fetchone()['count']
            boto3.client('cloudwatch',region_name=os.getenv('AWS_REGION','ap-south-1')).put_metric_data(Namespace=os.environ['METRICS_NAMESPACE'],MetricData=[{'MetricName':'WorkerAlive','Value':1,'Unit':'Count'},{'MetricName':'FailedReminders','Value':failed,'Unit':'Count'}])
        except Exception: logger.error('worker_metrics_failed')


if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    config.validate_production(); db.migrate()
    while True:
        try: tick()
        except Exception: logger.error('delivery_tick_failed',exc_info=False)
        time.sleep(30)
