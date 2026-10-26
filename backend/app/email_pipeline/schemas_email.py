"""Bounded Postmark-compatible input and inert RFC822 normalization."""
import base64,binascii,re
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
from html.parser import HTMLParser
from pathlib import PurePosixPath
from pydantic import BaseModel,Field
from fastapi import HTTPException

MAX_MESSAGE_BYTES=8*1024*1024
MAX_TEXT=200000

class InboundHeaderItem(BaseModel):
    Name:str=Field(max_length=128)
    Value:str=Field(max_length=8000)

class InboundAttachmentPayload(BaseModel):
    Name:str=Field(min_length=1,max_length=300)
    Content:str=Field(max_length=12*1024*1024)
    ContentType:str=Field(default='application/octet-stream',max_length=160)
    ContentLength:int|None=Field(default=None,ge=0,le=MAX_MESSAGE_BYTES)

class InboundEmail(BaseModel):
    From:str=Field(default='',max_length=500)
    To:str=Field(default='',max_length=2000)
    OriginalRecipient:str=Field(default='',max_length=500)
    MessageID:str=Field(default='',max_length=500)
    Subject:str=Field(default='',max_length=2000)
    TextBody:str=Field(default='',max_length=MAX_TEXT)
    HtmlBody:str=Field(default='',max_length=MAX_TEXT)
    RawEmail:str|None=Field(default=None,max_length=12*1024*1024)
    Headers:list[InboundHeaderItem]=Field(default_factory=list,max_length=100)
    Attachments:list[InboundAttachmentPayload]=Field(default_factory=list,max_length=6)

class Consent(BaseModel):
    consent:bool

class Simulation(BaseModel):
    scenario:str=Field(pattern='^(verification|gst|legal|phishing)$')

class _Text(HTMLParser):
    def __init__(self): super().__init__(convert_charrefs=True); self.parts=[]; self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','head'): self.hidden+=1
        if tag in ('br','p','div','tr'): self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style','head'): self.hidden=max(0,self.hidden-1)
    def handle_data(self,data):
        if not self.hidden: self.parts.append(data)

def plain_html(value):
    parser=_Text(); parser.feed(value); return ''.join(parser.parts)

def one_address(value):
    addresses=getaddresses([value])
    if len(addresses)!=1: raise HTTPException(422,'Exactly one envelope recipient is required.')
    address=addresses[0][1].strip().lower()
    if not re.fullmatch(r'[a-z0-9._+\-]+@[a-z0-9.\-]+\.[a-z]{2,}',address):
        raise HTTPException(422,'A valid envelope recipient is required.')
    return address

def safe_name(name):
    return PurePosixPath(name.replace('\\','/')).name[:200] or 'attachment.bin'

@dataclass
class NormalizedEmail:
    sender:str
    subject:str
    text:str
    headers:list[tuple[str,str]]
    attachments:list[tuple[str,bytes]]
    raw:bytes|None=None

def normalize(payload:InboundEmail):
    attachments=[]
    raw=None
    if payload.RawEmail:
        # Postmark supplies RFC822 text; signed adapters can also send base64 MIME.
        if re.match(r'^[\w-]+:',payload.RawEmail): raw=payload.RawEmail.encode('utf-8')
        else:
            try: raw=base64.b64decode(payload.RawEmail,validate=True)
            except (ValueError,binascii.Error): raise HTTPException(422,'RawEmail is not valid RFC822 text or base64.')
        if len(raw)>MAX_MESSAGE_BYTES: raise HTTPException(413,'Email exceeds the 8 MB decoded limit.')
        if raw.count(b'\n--')>64: raise HTTPException(422,'Email contains too many MIME parts.')
        message=BytesParser(policy=policy.default).parsebytes(raw)
        if len(message.get_all('From',[]))!=1: raise HTTPException(422,'Email must contain exactly one From header.')
        headers=[(str(k),str(v)) for k,v in message.items()]
        if len(headers)>100 or any(len(v)>8000 for _,v in headers): raise HTTPException(413,'Too many or oversized mail headers.')
        sender=str(message.get('From','')); subject=str(message.get('Subject',''))[:2000]
        body=message.get_body(preferencelist=('plain','html'))
        try: text=body.get_content() if body else ''
        except (LookupError,UnicodeError,ValueError): raise HTTPException(422,'Email body has an unsupported encoding.')
        if body and body.get_content_type()=='text/html': text=plain_html(text)
        for part in message.walk():
            if part.get_content_type()=='message/rfc822': raise HTTPException(415,'Attached emails must be imported separately as original messages.')
            if part.is_multipart(): continue
            if part.get_filename() or part.get_content_disposition()=='attachment':
                attachments.append((safe_name(part.get_filename() or 'attachment.bin'),part.get_payload(decode=True) or b''))
    else:
        sender=payload.From; subject=payload.Subject
        text=payload.TextBody or plain_html(payload.HtmlBody)
        headers=[(h.Name,h.Value) for h in payload.Headers]
        for attachment in payload.Attachments:
            try: content=base64.b64decode(attachment.Content,validate=True)
            except (ValueError,binascii.Error): raise HTTPException(422,'An attachment contains invalid base64.')
            if attachment.ContentLength is not None and attachment.ContentLength!=len(content):
                raise HTTPException(422,'An attachment length does not match its content.')
            attachments.append((safe_name(attachment.Name),content))
    if len(attachments)>6 or sum(len(content) for _,content in attachments)+len(str(text).encode('utf-8'))+len(subject.encode('utf-8'))>MAX_MESSAGE_BYTES:
        raise HTTPException(413,'Email attachments exceed the six-file / 8 MB limit.')
    if not isinstance(text,str) or len(text)>MAX_TEXT: raise HTTPException(413,'Email text exceeds 200,000 characters.')
    if not sender or not (text.strip() or attachments): raise HTTPException(422,'Email needs a sender and message body or attachment.')
    return NormalizedEmail(sender,subject,text,headers,attachments,raw)
