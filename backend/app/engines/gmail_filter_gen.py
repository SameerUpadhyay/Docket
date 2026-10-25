from datetime import datetime,timezone
from xml.etree.ElementTree import Element,SubElement,tostring,register_namespace
import re

def generate_gmail_filter_xml(user_inbound_webhook_email):
    if not re.fullmatch(r'[A-Za-z0-9._+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}',user_inbound_webhook_email):
        raise ValueError('Enter a valid forwarding email address.')
    atom='http://www.w3.org/2005/Atom'
    apps='http://schemas.google.com/apps/2006'
    register_namespace('',atom)
    register_namespace('apps',apps)
    feed=Element('{'+atom+'}feed')
    SubElement(feed,'{'+atom+'}title').text='Docket.in legal notice filter'
    SubElement(feed,'{'+atom+'}updated').text=datetime.now(timezone.utc).isoformat()
    entry=SubElement(feed,'{'+atom+'}entry')
    SubElement(entry,'{'+atom+'}category',term='filter')
    SubElement(entry,'{'+atom+'}title').text='Forward matching statutory and legal notices'
    query='from:(incometax.gov.in OR gst.gov.in OR gstn.org.in OR cbic.gov.in OR tdscpc.gov.in OR mca.gov.in OR epfindia.gov.in OR esic.gov.in) OR subject:("Show Cause Notice" OR "Demand Notice" OR "Legal Notice" OR "Section 138" OR "DRC-01" OR "ASMT-10")'
    for name,value in [('hasTheWord',query),('forwardTo',user_inbound_webhook_email),('label','Docket-Notices')]:
        SubElement(entry,'{'+apps+'}property',name=name,value=value)
    return tostring(feed,encoding='utf-8',xml_declaration=True).decode()
