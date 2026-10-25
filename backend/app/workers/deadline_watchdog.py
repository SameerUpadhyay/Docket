"""Local milestone simulator. It does not send SMS, email or WhatsApp messages."""
from datetime import date,timedelta

def preview_alerts(notices,today=None):
    today=today or date.today()
    alerts=[]
    for item in notices:
        if not item.limitation or item.state in ('SUBMITTED_CLOSED','PHISHING_QUARANTINED'):
            continue
        deadline=date.fromisoformat(item.limitation.effective_legal_deadline)
        for n in (7,3,1):
            when=deadline-timedelta(days=n)
            if when>=today:
                alerts.append(dict(notice_id=item.id,milestone=f'T-{n}',date=when.isoformat(),time='09:00 IST',delivery='SIMULATED'))
    return sorted(alerts,key=lambda a:a['date'])
