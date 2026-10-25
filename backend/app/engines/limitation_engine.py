from datetime import date,datetime,timedelta
from zoneinfo import ZoneInfo
from app.models.schemas import LimitationComputation

def compute_statutory_limitation(date_of_issue_str,date_of_service_str,window_days,reference_today=None,*,allow_rollover=False,office_holidays=None):
    today=reference_today or datetime.now(ZoneInfo('Asia/Kolkata')).date()
    issue=date.fromisoformat(date_of_issue_str)
    service=date.fromisoformat(date_of_service_str) if date_of_service_str else issue
    if service<issue:
        raise ValueError('Service date cannot precede issue date.')
    if not 1<=window_days<=365:
        raise ValueError('Response window must be 1–365 days.')
    raw=service+timedelta(days=window_days)
    effective=raw
    reasons=[]
    holidays=office_holidays or {}
    if allow_rollover:
        while effective.weekday()==6 or effective in holidays:
            reasons.append(effective.isoformat()+' ('+('Sunday' if effective.weekday()==6 else holidays[effective])+')')
            effective+=timedelta(days=1)
    remaining=(effective-today).days
    alerts=[(effective-timedelta(days=n),n) for n in (7,3,1) if effective-timedelta(days=n)>=today]
    next_alert=f'T-{alerts[0][1]} · {alerts[0][0].isoformat()} · 09:00 IST' if alerts else 'Due today' if remaining==0 else f'Overdue by {abs(remaining)} days' if remaining<0 else 'No future milestone'
    return LimitationComputation(date_of_issue=issue.isoformat(),date_of_service=service.isoformat(),statutory_window_days=window_days,raw_expiry_date=raw.isoformat(),holiday_rollover_applied=bool(reasons),holiday_reason='Potential Sec. 10 adjustment: '+', '.join(reasons) if reasons else None,effective_legal_deadline=effective.isoformat(),days_remaining=remaining,next_watchdog_alert=next_alert)
