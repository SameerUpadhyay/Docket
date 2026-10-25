"""Explicitly consented English-only Textract OCR; never logs original bytes/text."""
import os
from fastapi import HTTPException
from botocore.config import Config

def detect(content,language_hint='en'):
    if language_hint!='en': raise HTTPException(422,'Textract does not support Hindi. Use the local Hindi/Devanagari path.')
    if len(content)>10*1024*1024: raise HTTPException(413,'This page exceeds Textract’s 10 MB limit. Split or rescan the document.')
    import boto3
    try:
        client=boto3.client('textract',region_name=os.getenv('AWS_REGION','ap-south-1'),config=Config(connect_timeout=5,read_timeout=25,retries={'mode':'standard','total_max_attempts':2}))
        result=client.detect_document_text(Document={'Bytes':content})
    except Exception:
        raise HTTPException(503,'Cloud OCR is unavailable. No partial extraction was accepted; retry or choose local OCR.') from None
    blocks=result.get('Blocks',[])
    lines=[b for b in blocks if b.get('BlockType')=='LINE']
    parents={child:line.get('Id') for line in lines for relation in line.get('Relationships',[]) if relation.get('Type')=='CHILD' for child in relation.get('Ids',[])}
    words=[]
    for block in blocks:
        if block.get('BlockType')!='WORD': continue
        box=block.get('Geometry',{}).get('BoundingBox',{})
        normalized={key.lower():box[key] for key in ('Left','Top','Width','Height') if key in box}
        word={'text':block.get('Text',''),'confidence':block.get('Confidence'),'bbox':normalized if len(normalized)==4 else None}
        if block.get('Id') in parents: word['line_key']=(parents[block['Id']],)
        words.append(word)
    return {'text':'\n'.join(b.get('Text','') for b in lines),'words':words,'engine':'aws-textract','language_coverage':['en'],'model_version':result.get('DetectDocumentTextModelVersion'),'flags':[]}
