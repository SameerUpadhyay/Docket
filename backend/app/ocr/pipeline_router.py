"""Authenticated OCR-first preview; creates no case or statutory deadline."""
from pathlib import Path
from fastapi import APIRouter,UploadFile,File,Form
from fastapi.concurrency import run_in_threadpool
from app import auth
from app.models import database
from app.engines.document_reader import extract_document_details
from app.engines.pii_scrubber import scrub_pii_before_llm
from app.uploads import validate_upload
from .bilingual_ocr_engine import analyze_extraction,redact_analysis
from .schemas_ocr import CompleteOcrTriagePayload
router=APIRouter(prefix='/api/ocr')

@router.post('/ingest-and-triage',response_model=CompleteOcrTriagePayload)
async def ingest(file:UploadFile=File(...),ocr_language:str=Form('auto')):
    auth.writable()
    from app.main import read_upload
    content=await read_upload(file); name=Path(file.filename or 'notice.txt').name
    await run_in_threadpool(validate_upload,content,name)
    result=await run_in_threadpool(extract_document_details,content,name,ocr_language,bool(database.preferences()['cloud_ocr']))
    analysis=analyze_extraction(result,name)
    _,mapping,_=scrub_pii_before_llm(result.text+'\n'+'\n'.join(result.qr))
    return redact_analysis(analysis,mapping)
