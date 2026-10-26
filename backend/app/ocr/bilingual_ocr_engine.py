"""Source-backed bilingual notice extraction. Unknown values remain null."""
import re,time,uuid,json,unicodedata
from decimal import Decimal
from .schemas_ocr import *
from .anchor_extractor import *
from app.engines.fraud_guard import run_forensic_authenticity_check

def classify(text,anchors):
    t=text.lower()
    if not run_forensic_authenticity_check(document_text=text,qr_decoded_payloads=anchors.qr_payloads).safe_to_process: return NoticeDomain.SUSPECTED_SCAM,'Suspicious notice'
    families=[(r'\b(?:c?gst|sgst|igst|gstr|asmt|drc)\b|माल और सेवा कर|जीएसटी',NoticeDomain.GST_NOTICE,'GST notice'),(r'\bincome\s+tax\b|\b143\s*\(1\)|आयकर',NoticeDomain.INCOME_TAX_NOTICE,'Income Tax notice'),(r'(?:section|धारा|u/s)\s*138\b|negotiable instruments|चेक बाउंस|परक्राम्य लिखत',NoticeDomain.CHEQUE_BOUNCE_SEC138,'Section 138 NI Act demand'),(r'\bepfo?\b|\besic\b|provident fund|भविष्य निधि|श्रम आयुक्त',NoticeDomain.LABOUR_EPFO_ESIC,'Labour / EPFO / ESIC notice'),(r'\bmca\b|registrar of companies|कंपनी रजिस्ट्रार',NoticeDomain.MINISTRY_CORPORATE_AFFAIRS,'Corporate affairs notice'),(r'\bfssai\b|municipal|नगर निगम',NoticeDomain.FSSAI_OR_MUNICIPAL,'Food safety / municipal notice'),(r'legal notice|कानूनी नोटिस|विधिक नोटिस',NoticeDomain.PRIVATE_LEGAL_NOTICE,'Private legal notice')]
    for pattern,domain,title in families:
        if re.search(pattern,t):
            if domain==NoticeDomain.GST_NOTICE:
                if re.search(r'drc\s*[-–]?\s*01\b',t): title='Form GST DRC-01'
                elif re.search(r'asmt\s*[-–]?\s*10\b',t): title='Form GST ASMT-10'
            return domain,title
    return NoticeDomain.UNCLASSIFIED,'Unclassified notice · professional review'

COLUMN_PATTERNS={
 'tax_head':r'tax\s*head|head|^act$|कर\s*शीर्ष',
 'tax_or_principal_inr':r'^tax(?:\s*(?:amount|principal))?$|principal|मूल|^कर$',
 'interest_inr':r'interest|ब्याज',
 'penalty_inr':r'penalty|दंड|शास्ति',
 'late_fee_inr':r'late\s*fee|विलंब',
 'row_total_inr':r'total|योग|कुल',
}
def parse_grids(layout,printed_totals=None):
    rows=[]; warnings=[]
    for page in layout:
        for grid in page.get('tables',[]):
            if not grid: continue
            header=None; start=0
            for i,cells in enumerate(grid[:3]):
                mapping={}
                for column,value in enumerate(cells):
                    value=normalize_indic_numerals(str(value or '')).replace('\n',' ').strip().lower()
                    for key,pattern in COLUMN_PATTERNS.items():
                        if re.search(pattern,value) and key not in mapping: mapping[key]=column
                if 'tax_head' in mapping and len(mapping)>=3: header=mapping; start=i+1; break
            if not header:
                # Reference/date boxes are grids too, but are not failed tax tables.
                labels=' '.join(str(cell or '') for cells in grid[:3] for cell in cells)
                if len(re.findall(r'\btax\b|\binterest\b|\bpenalty\b|\btotal\b|ब्याज|शास्ति|कुल',labels,re.I))>=2:
                    warnings.append(f"Page {page['page']}: table column labels could not be established.")
                continue
            for cells in grid[start:]:
                at=lambda key: cells[header[key]] if key in header and header[key]<len(cells) else None
                if any(re.fullmatch(r'\s*(?:grand\s+total|total|कुल|योग)\s*',str(cell or ''),re.I) for cell in cells):
                    value=money(at('row_total_inr'))
                    if printed_totals is not None and value is not None: printed_totals.append(value)
                    continue
                head=str(at('tax_head') or '').strip(' |')
                if not head or re.search(r'grand|total|कुल|योग',head,re.I): continue
                values={k:money(at(k)) for k in COLUMN_PATTERNS if k!='tax_head'}
                if not any(v is not None for v in values.values()): continue
                rows.append(TaxTableRow(tax_head=head,page_number=page['page'],provenance=page.get('provenance','source-grid'),**values))
    return rows,warnings

def labelled_date(text,labels):
    match=re.search(r'(?:'+labels+r')\s*[:\-]?\s*('+REGEX_ANCHORS['date_raw'].pattern+r')',text,re.I)
    if match: return date_iso(match.group(1))
    # Recognize a Hindi date *label* despite a misplaced matra. Digits and date
    # values are never corrected or inferred from this label heuristic.
    if 'दिनांक' in labels:
        base=lambda value: ''.join(c for c in unicodedata.normalize('NFD',value) if not unicodedata.category(c).startswith('M'))
        for line in text.splitlines():
            candidate=re.match(r'\s*([^\s:ः]+)\s*[:ः]\s*('+REGEX_ANCHORS['date_raw'].pattern+r')',line)
            if candidate and base(candidate.group(1))==base('दिनांक'): return date_iso(candidate.group(2))
    return None

def source_highlights(layout,anchors,total):
    highlights=[]
    targets=[('DIN / reference',a) for a in anchors.din_numbers]+[('GSTIN',a) for a in anchors.gstin_numbers]+[('PAN',a) for a in anchors.pan_numbers]+[('Section',a) for a in anchors.sections_cited]
    for page in layout:
        # Local/provider word detections retain their measured line membership.
        # Union their actual boxes so multiword labels (e.g. Total Demand) can
        # locate the printed source without making up a rectangle.
        groups={}
        for index,word in enumerate(page.get('words',[])):
            key=tuple(word['line_key']) if word.get('line_key') else ('single',index)
            groups.setdefault(key,[]).append(word)
        lines=[]
        for group in groups.values():
            located=[word for word in group if word.get('bbox')]
            if not located: continue
            located.sort(key=lambda word:word['bbox']['left'])
            left=min(word['bbox']['left'] for word in located);top=min(word['bbox']['top'] for word in located)
            right=max(word['bbox']['left']+word['bbox']['width'] for word in located);bottom=max(word['bbox']['top']+word['bbox']['height'] for word in located)
            lines.append({'text':' '.join(word['text'] for word in located),'bbox':{'left':left,'top':top,'width':right-left,'height':bottom-top},'provenance':located[0].get('provenance','source-ocr')})
        for line in lines:
            text=normalize_indic_numerals(line.get('text','')); box=line.get('bbox')
            if not box: continue
            labels=[(label,value) for label,value in targets if value.lower() in text.lower()]
            if re.search(r'grand\s+total|total\s+(?:demand|amount)|कुल\s*(?:मांग|राशि|देय)',text,re.I): labels.append(('Total demand',str(total) if total is not None else 'Needs confirmation'))
            if re.search(r'within\s+\d+\s*days|\d+\s*दिन|due date|reply by|अंतिम तिथि',text,re.I): labels.append(('Response period / date',text.strip()))
            top,left,bottom,right=[round(v*1000) for v in (box['top'],box['left'],box['top']+box['height'],box['left']+box['width'])]
            top,left,bottom,right=[max(0,min(1000,v)) for v in (top,left,bottom,right)]
            if top>=bottom or left>=right: continue
            for label,value in labels:
                highlights.append(BoundingBoxHighlight(label=label,extracted_value=value,page_number=page['page'],box_2d=(top,left,bottom,right),provenance=line.get('provenance','source-ocr')))
    return highlights

def analyze_extraction(extraction,filename):
    text=normalize_indic_numerals(extraction.text); anchors=extract_deterministic_anchors(extraction.text,extraction.qr)
    domain,form=classify(text,anchors)
    printed_totals=[]
    rows,warnings=parse_grids(extraction.layout,printed_totals)
    for page in extraction.quality.get('pages',[]):
        if 'LOW_CONFIDENCE' in page.get('flags',[]) or 'CRITICAL_TEXT_NEEDS_REVIEW' in page.get('flags',[]): warnings.append(f"Page {page['page']}: uncertain text/numbers were detected; verify references, dates and amounts in the source.")
        if 'REFERENCE_OCR_READINGS_DISAGREE' in page.get('flags',[]): warnings.append(f"Page {page['page']}: independent reference-number reads disagreed; confirm the DIN/GSTIN character by character.")
        if 'TEXT_LAYER_DISAGREEMENT' in page.get('flags',[]): warnings.append(f"Page {page['page']}: embedded text and visual OCR disagree. Compare the original before relying on either.")
        if 'CLOUD_UNAVAILABLE_LOCAL_FALLBACK' in page.get('flags',[]): warnings.append(f"Page {page['page']}: the cloud service was unavailable; the local fallback produced this result.")
    totals=re.findall(r'(?:grand\s+total(?:\s+demand)?|total\s+(?:demand|amount)|amount\s+(?:payable|demanded)|cheque\s+principal|कुल\s*(?:मांग|राशि|देय))\s*[:=]?\s*₹?\s*(\d[\d,]*(?:\.\d{1,2})?)',text,re.I)
    distinct=list(dict.fromkeys([money(t) for t in totals if money(t) is not None]+printed_totals))
    total=distinct[0] if len(distinct)==1 else None
    if len(distinct)>1: warnings.append('Conflicting labelled totals; no single demand amount was accepted.')
    math_ok,math_note=verify_tax_table_arithmetic(rows,total)
    periods=list(dict.fromkeys(int(m.group(1)) for m in re.finditer(r'(?<!\d)(\d{1,3})(?!\d)\s*\)?\s*(?:days\b|दिन(?![\u0900-\u097f]))',text,re.I) if 1<=int(m.group(1))<=365))
    period=periods[0] if len(periods)==1 else None
    if len(periods)>1: warnings.append('Multiple printed day periods were found; confirm which one governs the required response.')
    issue=labelled_date(text,r'(?m:^\s*(?:date(?:\s+of\s+issue)?|issue\s+date|जारी\s+दिनांक|दिनांक))')
    if issue is None:
        # DRC layouts often put the explicitly labelled issue date beside the
        # reference number. Do not promote dates in narrative/transaction rows.
        header_dates=[match.group(1) for match in re.finditer(r'^\s*(?:Reference\s+No\.?|SCN\s+Reference\s+No\.?)\s*:[^\n]*?\bDate\s*:\s*('+REGEX_ANCHORS['date_raw'].pattern+r')',text,re.I|re.M)]
        candidates=list(dict.fromkeys(date_iso(value) for value in header_dates if date_iso(value)))
        if len(candidates)==1: issue=candidates[0]
        elif len(candidates)>1: warnings.append('Conflicting reference-header dates; confirm the issue date against the original.')
    due=labelled_date(text,r'due\s+date|reply\s+by|respond\s+by|अंतिम\s+तिथि')
    criminal=domain==NoticeDomain.CHEQUE_BOUNCE_SEC138 or bool(re.search(r'criminal\s+prosecution|imprisonment|कारावास|आपराधिक',text,re.I))
    freeze=bool(re.search(r'bank\s+(?:account\s+)?(?:freeze|attachment)|e.?way\s+bill\s+(?:block|ब्लॉक)|कुर्क',text,re.I))
    urgency=TriageUrgency.PHISHING_LOCKOUT if domain==NoticeDomain.SUSPECTED_SCAM else TriageUrgency.RED if criminal or freeze or (total is not None and total>=200000) or (period is not None and period<=7) else TriageUrgency.AMBER
    if math_ok is False: warnings.append(math_note)
    if period is None: warnings.append('Response period was not established from the notice; no 15-day default was used.')
    if issue is None: warnings.append('Issue date was not established from a label; no sample date was inserted.')
    if domain==NoticeDomain.UNCLASSIFIED: warnings.append('Notice family is outside validated playbooks; professional review required.')
    languages=(['Hindi'] if anchors.devanagari_chars_present else [])+(['English'] if re.search('[A-Za-z]',text) else [])
    en=f'The document appears to be {form}. '+(f'A labelled amount of INR {total:,.2f} was found. ' if total is not None else 'The amount requires confirmation. ')+(f'A printed {period}-day period was detected. ' if period is not None else 'The response period requires confirmation. ')+'Confirm the allegation, service date and applicability with the original and a professional.'
    hi=f'यह दस्तावेज़ {form} से संबंधित हो सकता है। '+(f'इसमें INR {total:,.2f} की लेबल की गई राशि मिली है। ' if total is not None else 'राशि की पुष्टि आवश्यक है। ')+(f'{period} दिन की अवधि लिखी मिली है। ' if period is not None else 'जवाब की अवधि की पुष्टि आवश्यक है। ')+'मूल नोटिस से तथ्य, प्राप्ति की तारीख और लागू कानून की जाँच करें।'
    transcript=extraction.text
    for page in extraction.layout:
        for grid in page.get('tables',[]):
            if grid:
                clean=lambda cell:str(cell or '[UNREADABLE]').replace('|','/').replace('\n',' ')
                transcript+='\n\nReconstructed table from page '+str(page['page'])+' (check the source):\n'+'\n'.join('| '+' | '.join(clean(cell) for cell in row)+' |' for row in grid)
    structured=VisionOcrStructuredOutput(detected_languages=languages,notice_domain=domain,specific_form_code=form,din_or_reference_id=anchors.din_numbers[0] if anchors.din_numbers else None,date_of_issue_iso=issue,response_window_days=period,explicit_due_date_iso=due,statutory_sections_invoked=anchors.sections_cited,core_allegation_english=en,core_allegation_hindi=hi,tax_breakdown_table=rows,total_demand_inr=total,threatens_bank_attachment_or_eway_block=freeze,threatens_criminal_prosecution=criminal,recommended_action_tier='ADVOCATE_REVIEW' if criminal else 'PROFESSIONAL_REVIEW',required_documents_checklist=['Original notice and proof of receipt','Records supporting the relevant tax period or transaction','A verified reconciliation and submission acknowledgement'],draft_reply_skeleton='To [ISSUING_AUTHORITY]\nReference: '+(anchors.din_numbers[0] if anchors.din_numbers else '[NOTICE_REFERENCE]')+'\n[VERIFIED_FACTS]\n[RECONCILIATION_AND_SUPPORTING_RECORDS]\n[PROFESSIONAL_REVIEW_BEFORE_SIGNING]',full_markdown_transcript=transcript,key_highlights=source_highlights(extraction.layout,anchors,total))
    pages=extraction.quality.get('pages',[]); sharp=[p['sharpness'] for p in pages if p.get('sharpness') is not None]
    return CompleteOcrTriagePayload(document_id=uuid.uuid4().hex,filename=filename,page_count=extraction.quality.get('page_count',1),extraction_engine_used=' + '.join(dict.fromkeys(p['engine'] for p in pages)),image_quality_score=sum(sharp)/len(sharp) if sharp else None,deskew_angle_applied=max((abs(p.get('deskew_angle',0)) for p in pages),default=0),table_math_verified=math_ok,table_math_discrepancy_note=math_note,urgency=urgency,deterministic_anchors=anchors,structured_triage=structured,processing_latency_ms=extraction.quality.get('elapsed_ms',0),warnings=list(dict.fromkeys(warnings)),pages=pages)

def redact_analysis(analysis,mapping):
    # Reuse intake's exact redaction tokens for all nested transcripts/anchors.
    def clean(value):
        if isinstance(value,str):
            for token,original in sorted(mapping.items(),key=lambda item:len(item[1]),reverse=True):
                for variant in {original,normalize_indic_numerals(original)}: value=re.sub(re.escape(variant),lambda _:token,value,flags=re.I)
            return value
        if isinstance(value,list): return [clean(v) for v in value]
        if isinstance(value,dict): return {k:clean(v) for k,v in value.items()}
        return value
    return CompleteOcrTriagePayload.model_validate(clean(analysis.model_dump(mode='json')))

def run_bilingual_ocr_and_triage(file_bytes,filename,mime_type=None,api_key=None,allow_cloud=False):
    # Explicit environment/workspace consent controls cloud use; an API key alone
    # never authorizes sending the original document to a provider.
    from app.engines.document_reader import extract_document_details
    extraction=extract_document_details(file_bytes,filename,'en-hi',allow_cloud)
    return analyze_extraction(extraction,filename)
