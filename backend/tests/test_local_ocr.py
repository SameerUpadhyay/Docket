"""Optional macOS integration check: DOCKET_TEST_LOCAL_OCR=1 pytest ..."""
import os
from pathlib import Path
import pytest
from app.engines.document_reader import VISION_BINARY

@pytest.mark.skipif(os.getenv('DOCKET_TEST_LOCAL_OCR')!='1' or not VISION_BINARY.is_file(),reason='Enable optional macOS local OCR integration check.')
def test_image_only_qr_is_quarantined_before_ai(client,monkeypatch):
    def forbidden(*args): raise AssertionError('Quarantined image must not reach external AI')
    monkeypatch.setattr('app.main.triage_with_gemini',forbidden)
    image=(Path(__file__).parent/'fixtures'/'scam-qr.png').read_bytes()
    r=client.post('/api/notices/analyze',files={'file':('scam.png',image,'image/png')},data={'date_of_issue':'2026-10-24','date_of_service':'2026-10-24','window_days':1})
    assert r.status_code==200,r.text
    assert r.json()['severity']=='PHISHING_SCAM'
    assert r.json()['forensics']['fraud_risk_score']==100
    assert r.json()['triage'] is None
