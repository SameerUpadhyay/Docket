"""Bounded type inspection and optional private ClamAV INSTREAM scanning."""
import os,socket,struct
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile,BadZipFile
from PIL import Image
from fastapi import HTTPException
from app import config

def validate_upload(content,name):
    suffix=Path(name).suffix.lower()
    if suffix not in ('.pdf','.png','.jpg','.jpeg','.webp','.txt','.csv','.eml','.xlsx'): raise HTTPException(415,'Unsupported file format.')
    if content[:2] in (b'MZ',b'#!') or content[:4]==b'\x7fELF': raise HTTPException(415,'Executable content is not accepted.')
    try:
        if suffix=='.pdf':
            if not content.startswith(b'%PDF-'): raise ValueError()
            from pypdf import PdfReader
            pdf=PdfReader(BytesIO(content))
            if pdf.is_encrypted or len(pdf.pages)>12: raise ValueError()
            if any(key in str(pdf.trailer) for key in ('/JavaScript','/Launch','/EmbeddedFiles')): raise ValueError()
        elif suffix in ('.png','.jpg','.jpeg','.webp'):
            image=Image.open(BytesIO(content))
            if image.width*image.height>30_000_000 or image.format not in ('PNG','JPEG','WEBP'): raise ValueError()
            image.verify()
        elif suffix=='.xlsx':
            with ZipFile(BytesIO(content)) as archive:
                files=archive.infolist()
                if len(files)>2000 or sum(f.file_size for f in files)>30_000_000 or '[Content_Types].xml' not in archive.namelist(): raise ValueError()
                if any('vbaproject' in f.filename.lower() for f in files): raise ValueError()
        else:
            content.decode('utf-8-sig')
            if b'\x00' in content: raise ValueError()
    except Exception as exc:
        raise HTTPException(422,'File content does not match its type, is unsafe, or exceeds the 12-page PDF / 30 MP image limit.') from exc
    host=os.getenv('CLAMAV_HOST','')
    if not host:
        if config.PRODUCTION: raise HTTPException(503,'File screening is unavailable. Try again later.')
        return
    try:
        with socket.create_connection((host,int(os.getenv('CLAMAV_PORT','3310'))),timeout=30) as scanner:
            scanner.sendall(b'zINSTREAM\x00')
            for start in range(0,len(content),65536):
                chunk=content[start:start+65536]; scanner.sendall(struct.pack('!I',len(chunk))+chunk)
            scanner.sendall(struct.pack('!I',0))
            result=scanner.recv(4096)
            if b'FOUND' in result: raise HTTPException(422,'The file was rejected by malware screening.')
            if b'OK' not in result: raise OSError('Scanner did not return a clean result')
    except HTTPException: raise
    except OSError as exc: raise HTTPException(503,'File screening is unavailable. Try again later.') from exc
