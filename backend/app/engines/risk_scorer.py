import re
from app.models.schemas import SeverityTier

def calculate_deterministic_severity(forensics,triage,limitation):
    if not forensics.safe_to_process:
        return SeverityTier.PHISHING_SCAM,100
    text=triage.statutory_act_and_section+' '+triage.notice_type_title
    high=re.search(r'\b(?:73|74|138|148|45a|7a|14b)\b|drc-01|reg-17',text,re.I)
    score=40 if high else 25 if re.search(r'show.cause|asmt-10|139\(9\)|\b61\b',text,re.I) else 10
    days=limitation.days_remaining
    score+=30 if days<=3 else 22 if days<=7 else 12 if days<=15 else 5
    amount=triage.financial_demand_inr
    score+=20 if amount>=250000 else 12 if amount>=25000 else 6 if amount>0 else 0
    if triage.has_criminal_or_arrest_clause or triage.has_bank_freeze_or_eway_block_threat:
        score+=25
    score=min(score,99)
    tier=SeverityTier.RED if score>=65 or triage.has_criminal_or_arrest_clause else SeverityTier.AMBER if score>=32 else SeverityTier.GREEN
    return tier,score
