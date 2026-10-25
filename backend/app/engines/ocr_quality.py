"""Conservative OCR checks; model confidence is not document accuracy."""
import re,statistics
CRITICAL=re.compile(r'\d|\b(?:\d{1,4}[/.\-]\d{1,2}[/.\-]\d{1,4}|INR|Rs\.?|demand|amount|deadline|within|days|section|DIN|GSTIN|PAN|notice\s+no)\b|₹|दिनांक|राशि|धारा|दिन',re.I)

def plausible_text(text):
    return len(text.strip())>=40 and sum(c.isalnum() for c in text)/max(1,len(text))>.45 and '\ufffd' not in text

def detected_languages(text):
    return (['en'] if re.search('[A-Za-z]',text) else [])+(['hi'] if re.search('[\u0900-\u097f]',text) else [])

def page_report(number,text,engine,words=None,flags=None,language_coverage=None,qr_checked=False,elapsed_ms=0):
    words=words or []; flags=list(flags or [])
    scores=[float(w['confidence']) for w in words if w.get('confidence') is not None]
    low=sum(s<90 for s in scores); critical=[]
    for word in words:
        score=word.get('confidence')
        if CRITICAL.search(word.get('text','')) and score is not None and score<95:
            critical.append({'confidence':round(score,2),'bbox':word.get('bbox')})
    if not text.strip(): flags.append('NO_TEXT')
    elif len(text.strip())<80: flags.append('SPARSE_TEXT')
    if '[UNREADABLE]' in text: flags.append('UNREADABLE_TEXT')
    if '\ufffd' in text: flags.append('INVALID_CHARACTERS')
    if scores and (statistics.mean(scores)<90 or low/max(1,len(scores))>.1): flags.append('LOW_CONFIDENCE')
    if critical: flags.append('CRITICAL_TEXT_NEEDS_REVIEW')
    if not scores and engine not in ('text-file','pdf-text'): flags.append('CONFIDENCE_UNAVAILABLE')
    if not qr_checked and engine!='text-file': flags.append('QR_SCREENING_UNAVAILABLE')
    return {'page':number,'engine':engine,'characters':len(text),'word_count':len(text.split()),'mean_confidence':round(statistics.mean(scores),2) if scores else None,'low_confidence_words':low,'critical_regions':critical,'flags':list(dict.fromkeys(flags)),'language_coverage':language_coverage or [],'detected_languages':detected_languages(text),'qr_checked':qr_checked,'elapsed_ms':round(elapsed_ms)}

def report(pages,elapsed_ms,language_hint):
    return {'version':'ocr-v2','requested_languages':language_hint,'detected_languages':list(dict.fromkeys(language for page in pages for language in page.get('detected_languages',[]))),'page_count':len(pages),'pages':pages,'elapsed_ms':round(elapsed_ms),'requires_review':True,'quality_status':'NEEDS_REVIEW' if any(p['flags'] for p in pages) else 'EXTRACTED_REQUIRES_FACT_CHECK','confidence_note':'Recognizer confidence is not measured accuracy or legal correctness.','coverage_complete':all(p['characters']>0 or 'VISUALLY_BLANK' in p['flags'] for p in pages)}
