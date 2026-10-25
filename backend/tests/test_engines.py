from datetime import date
from xml.etree.ElementTree import fromstring
from app.engines.fraud_guard import run_forensic_authenticity_check
from app.engines.limitation_engine import compute_statutory_limitation
from app.engines.pii_scrubber import scrub_pii_before_llm
from app.engines.gmail_filter_gen import generate_gmail_filter_xml
from app.engines.risk_scorer import calculate_deterministic_severity
from app.models.schemas import LLMTriageExtraction
from app.config import DATA_DIR
import json,pytest


def test_phishing_quarantine():
    f=run_forensic_authenticity_check('GSTN <compliance-alert@gst-portal-verify.in>','','GST suspension. Pay immediately upi://pay?pa=gst.penalty.desk@okicici&am=14999')
    assert f.verdict=='PHISHING_SCAM' and f.fraud_risk_score==100 and not f.safe_to_process
    assert len(f.scam_flags)>=2


def test_untrusted_authentication_headers_cannot_verify():
    f=run_forensic_authenticity_check('sender@cbic.gov.in','dkim=pass; spf=pass','CGST DIN: CBIC-20261067B892104432')
    assert f.din_format_valid and f.verdict=='SUSPICIOUS_UNVERIFIED'
    assert f.dkim_passed is None and f.spf_passed is None


def test_official_suffix_spoof_is_untrusted():
    f=run_forensic_authenticity_check('GSTN <officer@gst.gov.in.attacker.example>','','GST notice')
    assert f.verdict!='VERIFIED_GOV'


def test_epfo_sunday_adjustment_is_explicit():
    raw=compute_statutory_limitation('2026-10-17','2026-10-17',15,date(2026,10,24))
    assert raw.effective_legal_deadline=='2026-11-01' and not raw.holiday_rollover_applied
    adjusted=compute_statutory_limitation('2026-10-17','2026-10-17',15,date(2026,10,24),allow_rollover=True)
    assert adjusted.raw_expiry_date=='2026-11-01'
    assert adjusted.effective_legal_deadline=='2026-11-02' and adjusted.days_remaining==9
    assert adjusted.requires_review


def test_service_date_starts_clock_and_consecutive_closures():
    l=compute_statutory_limitation('2026-10-01','2026-10-17',15,date(2026,10,24),allow_rollover=True,office_holidays={date(2026,11,2):'Office holiday'})
    assert l.effective_legal_deadline=='2026-11-03'
    with pytest.raises(ValueError): compute_statutory_limitation('2026-10-17','2026-10-01',15)


def test_today_milestone_not_skipped():
    l=compute_statutory_limitation('2026-10-15','2026-10-15',15,date(2026,10,23))
    assert l.next_watchdog_alert.startswith('T-7')


def test_scrubber_duplicate_and_overlap():
    raw='ABCDE1234F and abcde1234f; 2345 6789 0123; 2345-6789-0123; Account No: 987654321012; 27ABCDE1234F1Z5; +91 9876543210; a@example.in'
    safe,mapping,count=scrub_pii_before_llm(raw)
    for secret in ('ABCDE1234F','abcde1234f','2345 6789 0123','987654321012','27ABCDE1234F1Z5','9876543210','a@example.in'):
        assert secret not in safe
    assert count==len(mapping)
    for key,value in mapping.items(): safe=safe.replace(key,value)
    assert safe==raw


def test_xml_escaping_and_validation():
    xml=generate_gmail_filter_xml('notices+legal@example.in')
    root=fromstring(xml)
    props={p.attrib['name']:p.attrib['value'] for p in root.iter('{http://schemas.google.com/apps/2006}property')}
    assert props['forwardTo']=='notices+legal@example.in'
    assert '"Legal Notice"' in props['hasTheWord']
    with pytest.raises(ValueError): generate_gmail_filter_xml("bad' /><evil>")


def test_section_number_matching_is_not_substring():
    data=json.loads((DATA_DIR/'statutory_playbooks.json').read_text())[0]['triage']
    data.update(statutory_act_and_section='Section 173 · Other Act',notice_type_title='Routine intimation',financial_demand_inr=0,has_criminal_or_arrest_clause=False)
    t=LLMTriageExtraction.model_validate(data)
    f=run_forensic_authenticity_check(document_text='Routine private notice')
    l=compute_statutory_limitation('2026-10-01','2026-10-01',60,date(2026,10,24))
    assert calculate_deterministic_severity(f,t,l)[1]==15
