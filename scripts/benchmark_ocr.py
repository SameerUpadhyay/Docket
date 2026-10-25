#!/usr/bin/env python3
"""Real-engine synthetic benchmark. Never sends pages to an external provider."""
import json,sys,time,statistics
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'backend'),str(root/'backend/tests')]
from generate_synthetic_notices import create_bilingual_gst_drc01_pdf,create_skewed_camera_photo_from_pdf,create_sec138_cheque_bounce_pdf,create_quishing_scam_notice_pdf
from app.ocr.bilingual_ocr_engine import run_bilingual_ocr_and_triage
from app.engines.document_reader import _render_pdf
folder=root/'output'/'ocr';folder.mkdir(parents=True,exist_ok=True)
source=create_bilingual_gst_drc01_pdf()
cases=[('bilingual-digital.pdf',source,{'total':'160000.00','period':15,'issue':'2026-10-15','din':'CBIC-20261077Z901234567','gstin':'27AABCU9603R1ZM','math':True}),('bilingual-scan.png',_render_pdf(source)[0],{'total':'160000.00','period':15,'issue':'2026-10-15','din':'CBIC-20261077Z901234567','gstin':'27AABCU9603R1ZM','math':True}),('bilingual-skewed.png',create_skewed_camera_photo_from_pdf(source),{'total':'160000.00','period':15,'issue':'2026-10-15','din':'CBIC-20261077Z901234567','gstin':'27AABCU9603R1ZM','math':True}),('cheque-138.pdf',create_sec138_cheque_bounce_pdf(),{'total':'350000.00','period':15,'domain':'CHEQUE_BOUNCE_SEC138','urgency':'RED'}),('scam-vector-qr.pdf',create_quishing_scam_notice_pdf(qr_only=True),{'urgency':'PHISHING_LOCKOUT'})]
results=[]
for name,content,expected in cases:
    started=time.perf_counter()
    try:
        analysis=run_bilingual_ocr_and_triage(content,name,allow_cloud=False)
        actual={'total':str(analysis.structured_triage.total_demand_inr),'period':analysis.structured_triage.response_window_days,'issue':analysis.structured_triage.date_of_issue_iso,'domain':analysis.structured_triage.notice_domain.value,'urgency':analysis.urgency.value,'din':analysis.deterministic_anchors.din_numbers,'gstin':analysis.deterministic_anchors.gstin_numbers,'math':analysis.table_math_verified}
        checks={key:(value in actual[key] if key in ('din','gstin') else actual[key]==value) for key,value in expected.items()}
        result={'file':name,'engine':analysis.extraction_engine_used,'elapsed_ms':round((time.perf_counter()-started)*1000),'checks':checks,'all_checks_passed':all(checks.values()),'review_required':analysis.review_required}
        (folder/(name+'.analysis.json')).write_text(analysis.model_dump_json(indent=2))
        (folder/name).write_bytes(content)
    except Exception as error:
        result={'file':name,'elapsed_ms':round((time.perf_counter()-started)*1000),'all_checks_passed':False,'error_type':type(error).__name__}
    results.append(result);print(name,'PASS' if result['all_checks_passed'] else 'NEEDS WORK',result['elapsed_ms'],'ms',flush=True)
report={'scope':'Five fictional synthetic documents, local desktop engine only. Not a real-notice accuracy certification. No model/provider/device accuracy percentage is asserted.','results':results,'median_ms':round(statistics.median(r['elapsed_ms'] for r in results)),'maximum_ms':max(r['elapsed_ms'] for r in results),'live_cloud_ocr_tested':False,'physical_android_ocr_tested':False}
(folder/'benchmark.json').write_text(json.dumps(report,indent=2)+'\n')
print('Report:',folder/'benchmark.json')
