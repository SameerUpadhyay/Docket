"""TLS SMTP transport; explicit private file sink in development only."""
import os,smtplib,ssl,uuid
from email.message import EmailMessage
from pathlib import Path
from app import config

def _send_email(address,subject,text):
    message=EmailMessage()
    message['From']=config.MAIL_FROM
    message['To']=address
    message['Subject']=subject
    message.set_content(text)
    if config.MAIL_TRANSPORT=='ses':
        import boto3
        options={'ConfigurationSetName':config.SES_CONFIGURATION_SET} if config.SES_CONFIGURATION_SET else {}
        boto3.client('sesv2',region_name=os.getenv('AWS_REGION','ap-south-1')).send_email(FromEmailAddress=config.MAIL_FROM,Destination={'ToAddresses':[address]},Content={'Raw':{'Data':message.as_bytes()}},**options)
        return
    if not config.SMTP_HOST:
        if config.PRODUCTION: raise RuntimeError('Email delivery is not configured')
        folder=Path(config.DATABASE_PATH).parent/'dev-outbox'
        folder.mkdir(mode=0o700,parents=True,exist_ok=True)
        path=folder/(uuid.uuid4().hex+'.eml')
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream: stream.write(message.as_bytes())
        return
    smtp=smtplib.SMTP_SSL(config.SMTP_HOST,config.SMTP_PORT,timeout=20,context=ssl.create_default_context()) if config.SMTP_PORT==465 else smtplib.SMTP(config.SMTP_HOST,config.SMTP_PORT,timeout=20)
    with smtp:
        if config.SMTP_PORT!=465: smtp.starttls(context=ssl.create_default_context())
        if config.SMTP_USER: smtp.login(config.SMTP_USER,config.SMTP_PASSWORD)
        smtp.send_message(message)


def send_email(address,subject,text):
    try: _send_email(address,subject,text)
    except Exception:
        from fastapi import HTTPException
        raise HTTPException(503,'Email delivery is temporarily unavailable. Try resending the code later.') from None
