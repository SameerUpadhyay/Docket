from decimal import Decimal
from io import BytesIO
from pathlib import Path
import pytest
from pypdf import PdfWriter,PdfReader
from app.ocr.anchor_extractor import normalize_indic_numerals,extract_deterministic_anchors,verify_tax_table_arithmetic
from app.ocr.schemas_ocr import TaxTableRow,BoundingBoxHighlight
from app.ocr.bilingual_ocr_engine import run_bilingual_ocr_and_triage,analyze_extraction,redact_analysis
from app.engines.document_reader import extract_document_details,Extraction,tesseract_command
from app.engines.pii_scrubber import scrub_pii_before_llm
from generate_synthetic_notices import create_bilingual_gst_drc01_pdf,create_skewed_camera_photo_from_pdf,create_sec138_cheque_bounce_pdf,create_quishing_scam_notice_pdf


def test_devanagari_currency_dates_and_bounded_sections():
    text='दिनांक: १५/१०/२०२६, कुल मांग रु. १,६०,००० धारा ७३ के अंतर्गत; Section 173'
    normalized=normalize_indic_numerals(text)
    assert '15/10/2026' in normalized and '₹1,60,000' in normalized
    anchors=extract_deterministic_anchors(text,[])
    assert anchors.dates_detected_iso==['2026-10-15']
    assert 'धारा 73' in anchors.sections_cited
    assert 'Section 17' not in anchors.sections_cited

@pytest.mark.skipif(not tesseract_command(),reason='Install bilingual local OCR runtime for live image checks.')
def test_bilingual_gst_source_grid_and_actual_geometry():
    result=run_bilingual_ocr_and_triage(create_bilingual_gst_drc01_pdf(),'gst.pdf')
    assert result.structured_triage.notice_domain=='GST_NOTICE'
    assert result.structured_triage.specific_form_code=='Form GST DRC-01'
    assert result.structured_triage.total_demand_inr==Decimal('160000')
    assert result.table_math_verified is True
    assert len(result.structured_triage.tax_breakdown_table)==2
    assert result.structured_triage.response_window_days==15
    assert 'Hindi' in result.structured_triage.detected_languages
    assert result.structured_triage.date_of_issue_iso=='2026-10-15'
    assert 'CBIC-20261077Z901234567' in result.deterministic_anchors.din_numbers
    highlights=result.structured_triage.key_highlights
    assert highlights and all(h.provenance in ('native-text','source-ocr-recovery') for h in highlights)
    assert any(h.label=='Total demand' and h.box_2d[0]>400 for h in highlights)


def test_table_math_uses_independent_printed_totals_and_unknowns():
    rows=[TaxTableRow(tax_head='CGST',tax_or_principal_inr=50000,interest_inr=5000,penalty_inr=5000,late_fee_inr=0,row_total_inr=60000),TaxTableRow(tax_head='SGST',tax_or_principal_inr=50000,interest_inr=5000,penalty_inr=5000,late_fee_inr=0,row_total_inr=60000)]
    assert verify_tax_table_arithmetic(rows,150000)[0] is False
    assert verify_tax_table_arithmetic(rows,120000)[0] is True
    rows[0].row_total_inr=Decimal('60000.02')
    assert verify_tax_table_arithmetic(rows,120000)[0] is False
    assert verify_tax_table_arithmetic([],None)[0] is None
    assert verify_tax_table_arithmetic([TaxTableRow(tax_head='CGST')],0)[0] is None

@pytest.mark.skipif(not tesseract_command(),reason='Install bilingual local OCR runtime.')
def test_skewed_photo_actual_bilingual_ocr():
    image=create_skewed_camera_photo_from_pdf(create_bilingual_gst_drc01_pdf(),6)
    result=run_bilingual_ocr_and_triage(image,'camera.png')
    assert 4<result.deskew_angle_applied<8
    assert result.structured_triage.notice_domain=='GST_NOTICE'
    assert 'Hindi' in result.structured_triage.detected_languages
    assert result.structured_triage.total_demand_inr==Decimal('160000')
    assert result.table_math_verified is True

@pytest.mark.skipif(not tesseract_command(),reason='Install local OCR runtime.')
def test_section_138_demands_advocate_review():
    result=run_bilingual_ocr_and_triage(create_sec138_cheque_bounce_pdf(),'cheque.pdf')
    assert result.urgency=='RED'
    assert result.structured_triage.threatens_criminal_prosecution
    assert result.structured_triage.total_demand_inr==Decimal('350000')
    assert result.structured_triage.recommended_action_tier=='ADVOCATE_REVIEW'

@pytest.mark.skipif(not tesseract_command(),reason='Install local OCR runtime.')
def test_vector_qr_scam_quarantines_before_any_cloud(monkeypatch):
    monkeypatch.setenv('OCR_PROVIDER','gemini')
    monkeypatch.setattr('app.ocr.gemini_reader.detect',lambda *a,**k: (_ for _ in ()).throw(AssertionError('Cloud must not be called for local QR fraud')))
    result=run_bilingual_ocr_and_triage(create_quishing_scam_notice_pdf(qr_only=True),'scam.pdf',allow_cloud=True)
    assert result.urgency=='PHISHING_LOCKOUT'
    assert 'gst.recovery.officer@okaxis' in result.deterministic_anchors.upi_ids_detected


def test_no_default_date_amount_period_or_fabricated_boxes():
    extraction=extract_document_details('अज्ञात कार्यालय का पत्र। कृपया संपर्क करें।'.encode(),'unknown.txt')
    result=analyze_extraction(extraction,'unknown.txt')
    assert result.structured_triage.date_of_issue_iso is None
    assert result.structured_triage.response_window_days is None
    assert result.structured_triage.total_demand_inr is None
    assert result.structured_triage.key_highlights==[]
    assert result.table_math_verified is None
    assert result.urgency=='AMBER'


def test_invalid_model_coordinates_rejected():
    with pytest.raises(ValueError): BoundingBoxHighlight(label='date',extracted_value='candidate',page_number=1,box_2d=(90,50,20,100))


def test_nested_identifiers_and_transcripts_use_intake_redaction_tokens():
    text='GSTIN: 27ABCDE1234F1Z5 PAN ABCDE1234F; दिनांक १५/१०/२०२६'
    extraction=extract_document_details(text.encode(),'sample.txt')
    analysis=analyze_extraction(extraction,'sample.txt')
    _,mapping,_=scrub_pii_before_llm(text)
    redacted=redact_analysis(analysis,mapping).model_dump_json()
    assert 'ABCDE1234F' not in redacted and '27ABCDE1234F1Z5' not in redacted


def test_unreadable_second_page_is_not_silently_ignored(monkeypatch):
    from app.engines import document_reader as reader
    writer=PdfWriter(); writer.add_blank_page(595,842);writer.add_blank_page(595,842);stream=BytesIO();writer.write(stream)
    monkeypatch.setattr(reader,'_render_pdf',lambda *a,**k:[b'first',b'second'])
    monkeypatch.setattr('app.ocr.qr_forensics.extract_qr_payloads_from_images',lambda *a:[])
    def inspect(*a,**k):
        return {'text':'Readable first page with enough notice information and a response request.' if a[0]==b'first' else '', 'engine':'test-engine','words':[], 'qr_payloads':[], 'qr_checked':True,'language_coverage':['en','hi'],'flags':[]}
    monkeypatch.setattr(reader,'inspect_image',inspect)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as problem: reader.extract_document_details(stream.getvalue(),'mixed.pdf')
    assert problem.value.status_code==422 and '2' in problem.value.detail


def test_multiple_periods_are_candidates_not_a_guessed_deadline():
    source='Date: 15/10/2026\nThe statute mentions 30 days. Please pay within 15 days.\nReference 4567 दिनांक.'
    result=analyze_extraction(extract_document_details(source.encode(),'periods.txt'),'periods.txt')
    assert result.structured_triage.response_window_days is None
    assert result.structured_triage.date_of_issue_iso=='2026-10-15'


def test_zero_is_not_missing_and_printed_wrong_total_is_not_recomputed():
    from app.ocr.bilingual_ocr_engine import parse_grids
    layout=[{'page':1,'tables':[[['Tax Head','Tax','Interest','Penalty','Late Fee','Total'],['CGST','0','0','0','0','0']]]}]
    rows,_=parse_grids(layout)
    assert verify_tax_table_arithmetic(rows,0)[0] is True
    rows[0].row_total_inr=Decimal('1')
    assert verify_tax_table_arithmetic(rows,0)[0] is False


def test_ocr_first_endpoint_requires_membership_and_has_no_fake_defaults(client):
    response=client.post('/api/ocr/ingest-and-triage',files={'file':('unknown.txt','अज्ञात कार्यालय का पत्र।'.encode())})
    assert response.status_code==200,response.text
    assert response.json()['structured_triage']['response_window_days'] is None
    assert response.json()['structured_triage']['date_of_issue_iso'] is None


@pytest.mark.parametrize('consent',[False,True])
def test_six_page_coverage_and_explicit_cloud_consent(monkeypatch,consent):
    from PIL import Image
    from app.engines import document_reader as reader
    writer=PdfWriter()
    images=[]
    for page in range(6):
        writer.add_blank_page(595,842)
        image=Image.new('RGB',(40,40),(page,255,255)); output=BytesIO();image.save(output,format='PNG');images.append(output.getvalue())
    source=BytesIO();writer.write(source)
    monkeypatch.setenv('OCR_PROVIDER','gemini')
    monkeypatch.setattr(reader,'_render_pdf',lambda *a,**k:images)
    monkeypatch.setattr('app.ocr.qr_forensics.extract_qr_payloads_from_images',lambda *a:[])
    def inspect(content,**options):
        assert options['cloud'] is consent
        page=Image.open(BytesIO(content)).getpixel((0,0))[0]+1
        return {'text':f'PAGE {page}: Complete notice text with a labelled response request and reference for source review.', 'engine':'gemini-vision' if consent else 'tesseract','words':[], 'language_coverage':['en','hi'],'qr_checked':True}
    monkeypatch.setattr(reader,'inspect_image',inspect)
    result=reader.extract_document_details(source.getvalue(),'six-pages.pdf',allow_cloud=consent)
    assert result.quality['page_count']==6
    assert result.quality['coverage_complete'] is True
    assert [item['page'] for item in result.layout]==list(range(1,7))
    assert all(f'PAGE {page}:' in result.text for page in range(1,7))
    assert result.text.index('PAGE 5:')<result.text.index('PAGE 6:')


def test_cloud_adapter_rejects_invalid_source_geometry_without_partial_output(monkeypatch):
    from types import SimpleNamespace
    from google import genai
    from fastapi import HTTPException
    from app.ocr.gemini_reader import detect
    closed=[]
    def generate(**arguments):
        assert arguments['config'].response_mime_type=='application/json'
        return SimpleNamespace(text='{"transcript":"A notice transcript", "lines":[{"text":"Date 15/10/2026","box_2d":[900,20,100,50]}]}')
    monkeypatch.setenv('GEMINI_API_KEY','fictional-test-key')
    monkeypatch.setattr(genai,'Client',lambda **k:SimpleNamespace(models=SimpleNamespace(generate_content=generate),close=lambda:closed.append(True)))
    with pytest.raises(HTTPException) as problem: detect(b'fictional-image')
    assert problem.value.status_code==503
    assert 'fictional-test-key' not in problem.value.detail
    assert closed==[True]


@pytest.mark.skipif(not tesseract_command(),reason='Install bilingual local OCR runtime.')
def test_scanned_separated_cell_borders_and_measured_multiword_highlight():
    from app.engines.document_reader import _render_pdf
    source=_render_pdf(create_bilingual_gst_drc01_pdf())[0]
    result=run_bilingual_ocr_and_triage(source,'scan.png')
    rows=result.structured_triage.tax_breakdown_table
    assert [row.tax_head for row in rows]==['CGST','SGST']
    assert all(row.late_fee_inr==0 and row.row_total_inr==80000 for row in rows)
    assert result.table_math_verified is True
    total=[highlight for highlight in result.structured_triage.key_highlights if highlight.label=='Total demand']
    assert total and total[0].provenance=='source-ocr' and total[0].box_2d[0]>400
    assert result.review_required is True


def test_textract_adapter_maps_actual_provider_boxes_and_line_relationships(monkeypatch):
    from types import SimpleNamespace
    import boto3
    from app.engines.textract_reader import detect
    from app.ocr.bilingual_ocr_engine import source_highlights
    from app.ocr.schemas_ocr import DeterministicAnchors
    blocks=[{'BlockType':'LINE','Id':'line1','Text':'Total Demand 160000','Relationships':[{'Type':'CHILD','Ids':['a','b','c']}]}]
    for index,text in enumerate(['Total','Demand','160000']):
        blocks.append({'BlockType':'WORD','Id':['a','b','c'][index],'Text':text,'Confidence':98,'Geometry':{'BoundingBox':{'Left':.1+index*.15,'Top':.6,'Width':.12,'Height':.02}}})
    monkeypatch.setattr(boto3,'client',lambda *a,**k:SimpleNamespace(detect_document_text=lambda **arguments:{'Blocks':blocks}))
    result=detect(b'fictional-page')
    assert result['words'][0]['bbox']=={'left':.1,'top':.6,'width':.12,'height':.02}
    highlights=source_highlights([{'page':2,'words':result['words']}],DeterministicAnchors(),Decimal('160000'))
    assert highlights[0].page_number==2
    assert highlights[0].box_2d==(600,100,620,520)


@pytest.mark.parametrize('text,expected',[
    ('Date: 15/10/2026\nPlease respond within 15 days. English notice.', ['en']),
    ('दिनांक: १५/१०/२०२६\nप्राप्ति के १५ दिन के भीतर अपना स्पष्टीकरण प्रस्तुत करें।', ['hi']),
    ('GST Notice दिनांक: १५/१०/२०२६\nPlease respond within 15 days.', ['en','hi']),
])
def test_automatic_mode_detects_scripts_without_a_language_prompt(text,expected):
    result=extract_document_details(text.encode(),'notice.txt','auto')
    assert result.quality['requested_languages']=='auto'
    assert result.quality['detected_languages']==expected
    assert result.quality['coverage_complete'] is True


def test_preview_defaults_to_automatic_ocr(client):
    response=client.post('/api/ocr/ingest-and-triage',files={'file':('notice.txt','GST Notice दिनांक: १५/१०/२०२६\nPlease respond within 15 days.'.encode())})
    assert response.status_code==200,response.text
    assert response.json()['structured_triage']['detected_languages']==['Hindi','English']
