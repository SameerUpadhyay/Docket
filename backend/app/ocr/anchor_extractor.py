import re
from datetime import datetime
from decimal import Decimal,InvalidOperation
from .schemas_ocr import DeterministicAnchors,TaxTableRow
DEVANAGARI_TO_ASCII=str.maketrans('०१२३४५६७८९','0123456789')
REGEX_ANCHORS={
 'din':re.compile(r'\b(?:CBIC[-\s]?[0-9]{6}[A-Z0-9]{10,14}|ITBA/[A-Z0-9/()\-]{14,45}|DIN[\s:\-]+[A-Z0-9/\-]{12,35})\b',re.I),
 'gstin':re.compile(r'\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b',re.I),
 'pan':re.compile(r'\b[A-Z]{5}[0-9]{4}[A-Z]\b',re.I),
 'section':re.compile(r'(?:\bSection\b|\bSec\.?|\bu/s\b|धारा)\s*([0-9]{1,3}[A-Z]?(?:\s*\([0-9A-Za-z]+\))*)(?!\d)',re.I),
 'date_raw':re.compile(r'(?<!\d)(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{4}|\d{4}[/\-.]\d{1,2}[/\-.]\d{1,2})(?!\d)'),
 'upi':re.compile(r'\b[a-zA-Z0-9._\-]{2,64}@(?:okaxis|okhdfcbank|okicici|oksbi|ybl|ibl|axl|paytm|upi|apl|barodampay|idfcbank)\b',re.I),
}
def normalize_indic_numerals(text):
    return re.sub(r'(?<![A-Za-z])(?:Rs\.?|INR|रु\.?|रुपये)\s*','₹',text.translate(DEVANAGARI_TO_ASCII),flags=re.I)
def date_iso(value):
    for fmt in ('%d-%m-%Y','%Y-%m-%d'):
        try: return datetime.strptime(value.replace('/','-').replace('.','-'),fmt).date().isoformat()
        except ValueError: pass
    return None
def extract_deterministic_anchors(raw_text,qr_payloads):
    text=normalize_indic_numerals(raw_text); combined=text+'\n'+'\n'.join(qr_payloads)
    found=lambda key: list(dict.fromkeys(m.group(0).strip() for m in REGEX_ANCHORS[key].finditer(combined if key in ('din','gstin','pan','upi') else text)))
    return DeterministicAnchors(din_numbers=list(dict.fromkeys(re.sub(r'^DIN[\s:\-]+(?=CBIC|ITBA)','',value,flags=re.I) for value in found('din'))),gstin_numbers=found('gstin'),pan_numbers=found('pan'),sections_cited=found('section'),dates_detected_iso=list(dict.fromkeys(d for m in REGEX_ANCHORS['date_raw'].finditer(text) if (d:=date_iso(m.group())))),qr_payloads=qr_payloads,upi_ids_detected=found('upi'),devanagari_chars_present=bool(re.search('[\u0900-\u097f]',raw_text)))
def money(value):
    text=normalize_indic_numerals(str(value or '')).replace('₹','').replace(',','').strip()
    if text in ('-','—','Nil','NIL','nil'): return Decimal('0.00')
    if not re.fullmatch(r'\d+(?:\.\d{1,2})?',text): return None
    try: return Decimal(text).quantize(Decimal('.01'))
    except InvalidOperation: return None

def verify_tax_table_arithmetic(rows:list[TaxTableRow],claimed_total):
    if not rows: return None,'No reconstructable table; arithmetic was not verified.'
    total=Decimal('0.00')
    for i,row in enumerate(rows,1):
        parts=[row.tax_or_principal_inr,row.interest_inr,row.penalty_inr,row.late_fee_inr]
        if any(p is None for p in parts) or row.row_total_inr is None: return None,f'Row {i} has missing printed components or total; arithmetic is unverified.'
        computed=sum(parts,Decimal('0')).quantize(Decimal('.01'))
        if abs(computed-row.row_total_inr)>Decimal('.01'): return False,f'Row {i} ({row.tax_head}) components total INR {computed}, but the printed row total is INR {row.row_total_inr}.'
        total+=row.row_total_inr
    if claimed_total is None: return None,'No independently labelled grand total was found; the column sum was not verified.'
    if abs(total-Decimal(str(claimed_total)))>Decimal('.01'): return False,f'Vertical table total INR {total} differs from the independently extracted grand total INR {claimed_total}.'
    return True,'Printed row and grand totals agree arithmetically; source recognition still requires review.'
