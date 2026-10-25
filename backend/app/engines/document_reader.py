"""Page-aware OCR with bounded work, explicit language coverage and no silent truncation."""
import csv,json,os,shutil,subprocess,tempfile,time,threading
from dataclasses import dataclass,field
from io import BytesIO,StringIO
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,TimeoutError
from PIL import Image,ImageOps,ImageStat
from fastapi import HTTPException
from app.config import MAX_UPLOAD_BYTES
from app.engines.ocr_quality import plausible_text,page_report,report

VISION_BINARY=Path(__file__).resolve().parents[2]/'bin'/'vision-ocr'
MAX_SECONDS=75
_OCR_SLOTS=threading.BoundedSemaphore(int(os.getenv('OCR_MAX_CONCURRENT_DOCS','1')))

@dataclass
class Extraction:
    text:str
    qr:list[str]
    notes:list[str]
    quality:dict
    layout:list[dict]=field(default_factory=list)


def normalized_image(content):
    try:
        with Image.open(BytesIO(content)) as original:
            if original.width*original.height>30_000_000: raise ValueError()
            original.load()
            image=ImageOps.exif_transpose(original).convert('RGB')
        return image
    except Exception as exc: raise HTTPException(422,'Unreadable image or image exceeds 30 megapixels.') from exc


def image_bytes(image):
    output=BytesIO(); image.save(output,format='PNG'); return output.getvalue()


def _vision(path,qr_only=False):
    try:
        args=[str(VISION_BINARY),str(path)]+(['--qr-only'] if qr_only else [])
        response=subprocess.run(args,capture_output=True,timeout=40,check=True)
        return json.loads(response.stdout)
    except (subprocess.SubprocessError,ValueError): raise HTTPException(422,'Local OCR failed. Rescan clearly or use the configured cloud OCR.') from None


def tesseract_command():
    configured=os.getenv('TESSERACT_CMD') or shutil.which('tesseract')
    if configured: return configured
    local=Path(__file__).resolve().parents[3]/'.tools'/'ocr'/'bin'/'tesseract'
    return str(local) if local.is_file() else None


def _tesseract(path,language_hint,psm='3',numeric=False):
    model_dir=os.getenv('TESSDATA_PREFIX','')
    if not model_dir:
        local=Path(__file__).resolve().parents[3]/'.tools'/'tessdata'
        if local.is_dir(): model_dir=str(local)
    options=['--tessdata-dir',model_dir] if model_dir else []
    listing=subprocess.run([tesseract_command(),'--list-langs']+options,capture_output=True,timeout=5,check=True).stdout.decode().splitlines()
    wanted=['eng'] if language_hint=='en' else ['hin'] if language_hint=='hi' else ['eng','hin']
    available=[x for x in wanted if x in listing]
    if not available: raise HTTPException(503,'The requested OCR language model is not installed.')
    languages='+'.join(available)
    if numeric: options+=['-c','tessedit_char_whitelist=0123456789०१२३४५६७८९,.-']
    result=subprocess.run([tesseract_command(),str(path),'stdout','-l',languages,'--psm',psm]+options+['-c','tessedit_create_tsv=1'],capture_output=True,timeout=40,check=True,env=os.environ|{'OMP_THREAD_LIMIT':'1'})
    words=[]; lines={}
    for row in csv.DictReader(StringIO(result.stdout.decode('utf-8')),delimiter='\t'):
        if row.get('level')!='5' or not row.get('text','').strip(): continue
        key=tuple(row.get(k) for k in ('page_num','block_num','par_num','line_num'))
        text=row['text']; confidence=float(row['conf'])
        word={'text':text,'line_key':key,'confidence':confidence if confidence>=0 else None,'bbox':{k:int(row[k]) for k in ('left','top','width','height')}}
        words.append(word); lines.setdefault(key,[]).append(text)
    return {'text':'\n'.join(' '.join(line) for line in lines.values()),'words':words,'engine':'tesseract','language_coverage':[{'eng':'en','hin':'hi'}[x] for x in available],'flags':['LANGUAGE_MODEL_MISSING'] if len(available)!=len(wanted) else []}


def inspect_image(content,suffix='.png',language_hint='en-hi',cloud=False,cloud_content=None,text_optional=False):
    from app.ocr.image_preprocessor import prepare
    prepared=prepare(content)
    image=normalized_image(prepared.enhanced)
    flags=[]
    if min(image.size)<1000: flags.append('LOW_RESOLUTION')
    # Conservative blank detection; scanned/noisy pages are not assumed blank.
    small=image.convert('L').resize((200,200)); stats=ImageStat.Stat(small)
    visually_blank=stats.mean[0]>253 and stats.stddev[0]<1.5
    with tempfile.TemporaryDirectory(prefix='docket-ocr-') as temporary:
        source=Path(temporary)/'page.png'; source.write_bytes(image_bytes(image))
        from app.ocr.qr_forensics import extract_qr_payloads_from_images
        qr=extract_qr_payloads_from_images([prepared.source,prepared.enhanced]); qr_checked=True
        cached_vision=None
        if VISION_BINARY.is_file() and not tesseract_command() and not cloud:
            cached_vision=_vision(source,qr_only=cloud)
            qr=list(dict.fromkeys(qr+cached_vision.get('qr_payloads',[]))); qr_checked=True
        elif shutil.which('zbarimg'):
            try:
                response=subprocess.run(['zbarimg','--quiet','--raw',str(source)],capture_output=True,timeout=15)
                if response.returncode not in (0,4): raise ValueError()
                qr=list(dict.fromkeys(qr+response.stdout.decode('utf-8',errors='replace').splitlines())); qr_checked=True
            except (subprocess.SubprocessError,ValueError): raise HTTPException(422,'QR inspection failed. No partial result was accepted.') from None
        if cloud and qr:
            from app.engines.fraud_guard import run_forensic_authenticity_check
            if not run_forensic_authenticity_check(qr_decoded_payloads=qr).safe_to_process:
                cloud=False; flags.append('CLOUD_BYPASSED_FOR_SUSPICIOUS_QR')
                if cached_vision is not None: cached_vision=_vision(source)
        if cloud:
            try:
                if os.getenv('OCR_PROVIDER','local')=='gemini':
                    from app.ocr.gemini_reader import detect
                    data=detect(prepared.enhanced,language_hint)
                else:
                    from app.engines.textract_reader import detect
                    data=detect(cloud_content or (image_bytes(normalized_image(content)) if suffix=='.webp' or not content.startswith((b'\x89PNG',b'\xff\xd8',b'%PDF')) else content),language_hint)
            except HTTPException as exc:
                if exc.status_code<500 or not tesseract_command(): raise
                try: data=_tesseract(source,language_hint)
                except subprocess.SubprocessError: raise HTTPException(422,'Cloud and local OCR failed. Rescan the page and retry; no partial result was accepted.') from None
                flags.append('CLOUD_UNAVAILABLE_LOCAL_FALLBACK')
        elif tesseract_command():
            try: data=_tesseract(source,language_hint)
            except subprocess.SubprocessError: raise HTTPException(422,'Local OCR timed out or failed. Rescan the page and retry.') from None
        elif cached_vision is not None:
            data=cached_vision|{'engine':'apple-vision','language_coverage':['en']}
            if language_hint!='en': flags.append('HINDI_MODEL_UNAVAILABLE')
        elif text_optional or visually_blank:
            data={'text':'','words':[],'engine':'blank-check','language_coverage':[]}
        else: raise HTTPException(503,'Local image OCR is unavailable. Install the OCR runtime or use an opted-in configured provider.')
    if visually_blank and not data.get('text','').strip() and not qr: flags.append('VISUALLY_BLANK')
    if data.get('engine')=='tesseract':
        # Independently reread Latin reference lines. This is image recognition,
        # never a Z/2 or O/0 string substitution. Disagreements remain visible.
        import re,cv2,numpy as np
        groups={}
        for word in data.get('words',[]): groups.setdefault(tuple(word.get('line_key',())),[]).append(word)
        rechecks=0
        for group in groups.values():
            line=' '.join(word['text'] for word in group)
            if not re.search(r'\bDIN\b|CBIC|ITBA|GSTIN',line,re.I) or rechecks>=3: continue
            rechecks+=1
            left=max(0,min(w['bbox']['left'] for w in group)-15); top=max(0,min(w['bbox']['top'] for w in group)-15)
            right=min(image.width,max(w['bbox']['left']+w['bbox']['width'] for w in group)+15); bottom=min(image.height,max(w['bbox']['top']+w['bbox']['height'] for w in group)+15)
            crop=image.crop((left,top,right,bottom)); crop=crop.resize((crop.width*2,crop.height*2))
            with tempfile.TemporaryDirectory(prefix='docket-reference-') as folder:
                path=Path(folder)/'reference.png'; path.write_bytes(image_bytes(crop)); reread=_tesseract(path,'en',psm='7')
            from app.ocr.anchor_extractor import extract_deterministic_anchors
            candidates=extract_deterministic_anchors(reread['text'],[])
            previous=extract_deterministic_anchors(line,[])
            for newer,older in [(candidates.din_numbers,previous.din_numbers),(candidates.gstin_numbers,previous.gstin_numbers)]:
                if len(newer)==1 and len(older)==1 and newer[0]!=older[0]:
                    flags.append('REFERENCE_OCR_READINGS_DISAGREE')
                    before=[w.get('confidence',0) or 0 for w in group if older[0] in w['text']]
                    after=[w.get('confidence',0) or 0 for w in reread['words'] if newer[0] in w['text']]
                    if before and after and max(after)>max(before)+3:
                        data['text']=data['text'].replace(older[0],newer[0])
                        for word in group: word['text']=word['text'].replace(older[0],newer[0])
        from app.ocr.table_grid import extract_ruled_tables
        data['tables']=extract_ruled_tables(prepared.enhanced,data.get('words',[]))
        from app.ocr.anchor_extractor import money
        # Border glyphs and unparseable numeric cells also warrant a second
        # recognition pass; they must not silently make an entire row disappear.
        damaged_borders=any(cell is None or '|' in str(cell) for grid in data['tables'] for row in grid for cell in row)
        unreadable_amounts=any(money(cell) is None for grid in data['tables'] for row in grid[1:] for cell in row[1:])
        if damaged_borders or unreadable_amounts:
            from app.ocr.table_grid import recover_grid_text
            def recognize_table(pixels,numeric=False):
                with tempfile.TemporaryDirectory(prefix='docket-table-') as temp:
                    path=Path(temp)/'table.png'; path.write_bytes(pixels)
                    return _tesseract(path,language_hint,psm='7' if numeric else '6',numeric=numeric)
            recovered=recover_grid_text(prepared.enhanced,recognize_table)
            if recovered: data['tables']=recovered; flags.append('TABLE_SECOND_PASS_REQUIRES_REVIEW')
    import cv2,numpy as np
    inverse=np.linalg.inv(prepared.transform)
    for word in data.get('words',[]):
        box=word.get('bbox')
        if not box: continue
        x,y,w,h=(box[k] for k in ('left','top','width','height'))
        if data.get('engine')!='tesseract': x,y,w,h=x*image.width,y*image.height,w*image.width,h*image.height
        projected=np.array([[x,y,1],[x+w,y,1],[x,y+h,1],[x+w,y+h,1]])@inverse.T
        points=projected[:,:2]/projected[:,2:3]
        left,top=np.maximum(points.min(axis=0),0); right,bottom=np.minimum(points.max(axis=0),[prepared.width,prepared.height])
        word['bbox']={'left':float(left/prepared.width),'top':float(top/prepared.height),'width':float(max(0,right-left)/prepared.width),'height':float(max(0,bottom-top)/prepared.height)}
    return data|{'perspective_corrected':prepared.perspective_corrected,'deskew_angle':prepared.angle,'sharpness':prepared.sharpness,'qr_payloads':qr,'qr_checked':qr_checked,'flags':data.get('flags',[])+flags}


def _render_pdf(content,only_page=None):
    """PDFium renders each page, including vector QR codes; no embedded-image cap."""
    import pypdfium2 as pdfium
    pages=[]
    try:
        with pdfium.PdfDocument(content) as document:
            if not 1<=len(document)<=12: raise ValueError('PDF must contain 1–12 pages')
            indices=range(len(document)) if only_page is None else [only_page-1]
            if only_page is not None and not 1<=only_page<=len(document): raise ValueError()
            for index in indices:
                page=document[index]
                try:
                    width,height=page.get_size()
                    if width<=0 or height<=0: raise ValueError()
                    scale=min(300/72,(30_000_000/(width*height))**.5)
                    bitmap=page.render(scale=scale)
                    try:
                        pixels=image_bytes(bitmap.to_pil())
                        if sum(map(len,pages))+len(pixels)>80*1024*1024: raise ValueError('Rendered document exceeds safe memory budget')
                        pages.append(pixels)
                    finally: bitmap.close()
                finally: page.close()
    except Exception: raise HTTPException(422,'PDF could not be completely rendered. Upload an unlocked, intact PDF with up to 12 pages.') from None
    return pages


def _extract_document_details(content,filename,language_hint='en-hi',allow_cloud=False):
    started=time.monotonic()
    requested_language=language_hint
    if language_hint not in ('auto','en','hi','en-hi'): raise HTTPException(422,'Choose English, Hindi or English + Hindi.')
    # Automatic mode recognizes both scripts in a single bilingual pass. It does
    # not guess from a filename or throw away mixed-script pages.
    if language_hint=='auto': language_hint='en-hi'
    extension=Path(filename).suffix.lower(); notes=[]; pages=[]; texts=[]; qr=[]
    if extension in ('.txt','.eml','.csv'):
        try: text=content.decode('utf-8-sig')
        except UnicodeDecodeError: raise HTTPException(422,'Text files must use UTF-8 encoding.')
        if not text.strip(): raise HTTPException(422,'The document contains no text.')
        pages=[page_report(1,text,'text-file',language_coverage=[language_hint])]
        return Extraction(text,[],['Text was supplied directly; check completeness against the original.'],report(pages,(time.monotonic()-started)*1000,requested_language))
    provider=os.getenv('OCR_PROVIDER','local')
    cloud=allow_cloud and (provider=='gemini' or provider=='textract' and language_hint=='en')
    if allow_cloud and provider=='textract' and language_hint!='en': notes.append('Textract does not support Hindi; this request used the local multilingual path.')
    if extension=='.pdf':
        try:
            from pypdf import PdfReader
            reader=PdfReader(BytesIO(content))
            if reader.is_encrypted or not 1<=len(reader.pages)<=12: raise ValueError()
            native=[page.extract_text(extraction_mode='layout') or '' for page in reader.pages]
        except Exception: raise HTTPException(422,'PDF text could not be read. Upload an unlocked PDF with up to 12 pages.') from None
        images=_render_pdf(content)
        from app.ocr.pdf_layout import extract_layout
        native_layout=extract_layout(content)
        native=[layout['text'] if plausible_text(layout.get('text','')) else text for layout,text in zip(native_layout,native)]
        provider_documents=[]
        for page in reader.pages:
            if cloud:
                from pypdf import PdfWriter
                writer=PdfWriter(); writer.add_page(page); output=BytesIO(); writer.write(output); provider_documents.append(output.getvalue())
            else: provider_documents.append(None)
    elif extension in ('.png','.jpg','.jpeg','.webp'):
        images=[content]; native=['']; provider_documents=[None]; native_layout=[{'words':[],'tables':[]}]
    else: raise HTTPException(415,'Supported intake: PDF, PNG, JPG, WEBP, TXT, CSV and EML.')
    from app.ocr.qr_forensics import extract_qr_payloads_from_images
    from app.engines.fraud_guard import run_forensic_authenticity_check
    if cloud:
        from app.ocr.image_preprocessor import prepare
        prescan=[]
        for image in images:
            prepared=prepare(image)
            prescan.extend(extract_qr_payloads_from_images([prepared.source,prepared.enhanced]))
        prescan=list(dict.fromkeys(prescan))
    else: prescan=extract_qr_payloads_from_images(images)
    if not run_forensic_authenticity_check(document_text='\n'.join(native),qr_decoded_payloads=prescan).safe_to_process:
        cloud=False; notes.append('Cloud OCR bypassed because local QR/text screening found scam signals.')
    qr.extend(prescan)
    def inspect(index):
        page_started=time.monotonic(); embedded=native[index]
        # PDF text is extracted without character substitution. The rendered page is
        # still locally QR screened; cloud OCR is used only for scanned/weak text.
        result=inspect_image(images[index],language_hint=language_hint,cloud=cloud and not plausible_text(embedded),cloud_content=provider_documents[index],text_optional=plausible_text(embedded))
        flags=list(result.get('flags',[])); chosen=result.get('text',''); engine=result.get('engine','local'); words=result.get('words',[])
        if plausible_text(embedded):
            if chosen.strip():
                from difflib import SequenceMatcher
                normalize=lambda t: ''.join(c.lower() for c in t if c.isalnum())
                if SequenceMatcher(None,normalize(embedded)[:12000],normalize(chosen)[:12000]).ratio()<.75: flags.append('TEXT_LAYER_DISAGREEMENT')
            chosen=embedded; engine='pdf-text'; words=[]
            # Complex-script PDFs can have valid visible glyphs but broken copy
            # text (e.g. an IPA glyph replacing a Hindi matra). Recover only those
            # measured source lines from independent visual OCR, never by editing
            # digits or guessing identifiers.
            import re
            recovered=False
            for line in native_layout[index].get('words',[]):
                value=line['text']
                if not re.search('[\u0900-\u097f]',value) or not re.search(r'[\u0250-\u02af]|[µ³þ](?=[\u0900-\u097f])',value): continue
                box=line['bbox']; matches=[]
                for word in result.get('words',[]):
                    b=word.get('bbox',{}); x=b.get('left',-1)+b.get('width',0)/2; y=b.get('top',-1)+b.get('height',0)/2
                    if box['left']-.01<=x<=box['left']+box['width']+.01 and box['top']-.008<=y<=box['top']+box['height']+.008: matches.append(word)
                matches.sort(key=lambda word:word['bbox']['left']); candidate=' '.join(word['text'] for word in matches)
                if re.search('[\u0900-\u097f]',candidate) and len(candidate)>=len(value)*.65:
                    line['text']=candidate; line['provenance']='source-ocr-recovery'; recovered=True
            if recovered:
                chosen='\n'.join(line['text'] for line in native_layout[index]['words'])
                engine='pdf-text-hybrid'; flags.append('NATIVE_GLYPH_TEXT_RECOVERED_REQUIRES_REVIEW')
        geometry=native_layout[index] if engine in ('pdf-text','pdf-text-hybrid') else {'words':result.get('words',[]),'tables':result.get('tables',[])}
        if engine not in ('pdf-text','pdf-text-hybrid') and language_hint!='en' and 'hi' not in result.get('language_coverage',[]) and 'VISUALLY_BLANK' not in flags and not result.get('qr_payloads'):
            raise HTTPException(503,'Hindi OCR is unavailable in the selected runtime. Install the Hindi model or select a configured bilingual cloud provider.')
        page=page_report(index+1,chosen,engine,words,flags,result.get('language_coverage',[]),result.get('qr_checked',False),(time.monotonic()-page_started)*1000)
        if 'VISUALLY_BLANK' in flags: page['flags']=[f for f in page['flags'] if f not in ('NO_TEXT','CONFIDENCE_UNAVAILABLE')]
        page['perspective_corrected']=result.get('perspective_corrected',False); page['deskew_angle']=result.get('deskew_angle',0); page['sharpness']=result.get('sharpness')
        return chosen,result.get('qr_payloads',[]),page,geometry|{'page':index+1}
    executor=ThreadPoolExecutor(max_workers=2,thread_name_prefix='docket-ocr')
    layouts=[]
    futures=[executor.submit(inspect,index) for index in range(len(images))]
    try:
        for index,future in enumerate(futures):
            left=MAX_SECONDS-(time.monotonic()-started)
            if left<=0: raise TimeoutError()
            text,codes,page,geometry=future.result(timeout=left)
            texts.append(text); qr.extend(codes); pages.append(page); layouts.append(geometry)
    except TimeoutError: raise HTTPException(504,'Document reading exceeded 75 seconds. Split the file into smaller parts and retry; no partial case was created.') from None
    finally: executor.shutdown(wait=False,cancel_futures=True)
    missing=[p['page'] for p in pages if not p['characters'] and 'VISUALLY_BLANK' not in p['flags']]
    from app.engines.fraud_guard import run_forensic_authenticity_check
    unsafe_qr=bool(qr) and not run_forensic_authenticity_check(qr_decoded_payloads=qr).safe_to_process
    if missing and not unsafe_qr: raise HTTPException(422,'Unreadable text on page(s) '+', '.join(map(str,missing))+'. Rescan or transcribe those pages; no partial case was created.')
    text='\n\n'.join(f'--- Page {index+1} ---\n{part}' for index,part in enumerate(texts)) if len(texts)>1 else texts[0]
    if not any(part.strip() for part in texts) and not qr: raise HTTPException(422,'No readable text was found. Use a clearer scan or paste a verified transcription.')
    quality=report(pages,(time.monotonic()-started)*1000,requested_language)
    notes.extend(['Every PDF page was rendered for inspection.' if extension=='.pdf' else 'Image orientation was normalized before local recognition.','OCR confidence is not measured accuracy. Confirm dates, amounts, references and statutory wording against the original.'])
    notes.extend(f"Page {p['page']}: "+', '.join(p['flags']) for p in pages if p['flags'])
    if cloud: notes.append('Cloud OCR was selected with owner consent. Original document images may be sent to the configured provider; summary consent is separate.')
    return Extraction(text,list(dict.fromkeys(qr)),notes,quality,layouts)


def extract_document_details(content,filename,language_hint='en-hi',allow_cloud=False):
    if not _OCR_SLOTS.acquire(blocking=False): raise HTTPException(429,'Document recognition is busy. Please retry shortly.')
    try: return _extract_document_details(content,filename,language_hint,allow_cloud)
    finally: _OCR_SLOTS.release()


def extract_document(content,filename):
    """Backward-compatible tuple interface for local callers."""
    result=extract_document_details(content,filename)
    return result.text,result.qr,result.notes
