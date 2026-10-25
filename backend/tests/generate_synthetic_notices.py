"""Fictional notices with a real Unicode Devanagari font, printed grid and QR.

Source documents are not operational legal templates. No real taxpayer data.
"""
from io import BytesIO
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Table,TableStyle
from reportlab.lib import colors
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF
from PIL import Image
import cv2,numpy as np
from itertools import groupby
from reportlab.pdfgen.canvas import bidiShapedText

FONT=Path(__file__).parent/'fonts'/'NotoSansDevanagari-Regular.ttf'
def font():
    if 'DocketHindi' not in pdfmetrics.getRegisteredFontNames(): pdfmetrics.registerFont(TTFont('DocketHindi',str(FONT),shapable=True))
    return 'DocketHindi'

def mixed_line(page,x,y,text,size=11):
    for ascii_run,characters in groupby(text,key=lambda c:ord(c)<128):
        chunk=''.join(characters); name='Helvetica' if ascii_run else font()
        page.setFont(name,size)
        _,width=bidiShapedText(chunk,fontName=name,fontSize=size,shaping=not ascii_run)
        page.drawString(x,y,chunk,shaping=not ascii_run); x+=width


def create_bilingual_gst_drc01_pdf(tampered=False):
    # HTML/Story uses HarfBuzz shaping and font fallback for intra-line code switches.
    # Helvetica-only insert_textbox cannot produce valid Hindi test evidence.
    import pymupdf
    total='1,50,000' if tampered else '1,60,000'
    html="""<h3>FICTIONAL OCR BENCHMARK - NOT A LEGAL NOTICE</h3>
    <p>कार्यालय अधीक्षक, केंद्रीय माल और सेवा कर (CGST)</p>
    <p>Office of the Superintendent, Central Goods and Services Tax</p>
    <p>DIN: CBIC-20261077Z901234567</p><p>दिनांक: १५/१०/२०२६</p>
    <p>GSTIN: 27AABCU9603R1ZM</p><h3>FORM GST DRC-01</h3>
    <p>कारण बताओ नोटिस - धारा ७३ (Section 73 of CGST Act, 2017)</p>
    <p>Tax Period: FY 2025-26 (Q2)</p>
    <p>GSTR-3B और GSTR-2B के मिलान में इनपुट टैक्स क्रेडिट का अंतर पाया गया।</p>
    <p>Discrepancy in Input Tax Credit reconciliation.</p>
    <table><tr><th>Tax Head</th><th>Tax</th><th>Interest</th><th>Penalty</th><th>Late Fee</th><th>Total</th></tr>
    <tr><td>CGST</td><td>65,000</td><td>8,500</td><td>6,500</td><td>0</td><td>80,000</td></tr>
    <tr><td>SGST</td><td>65,000</td><td>8,500</td><td>6,500</td><td>0</td><td>80,000</td></tr></table>
    <p><b>Grand Total Demand: INR TOTAL_PLACEHOLDER</b></p>
    <p>प्राप्ति के १५ दिन के भीतर अपना स्पष्टीकरण प्रस्तुत करें।</p>
    <p>Please respond within 15 days of receipt.</p>
    <p>An e-way bill block is stated; confirm applicability with a professional.</p>""".replace('TOTAL_PLACEHOLDER',total)
    css="@font-face{font-family:Hindi;src:url(NotoSansDevanagari-Regular.ttf)}body{font-family:Hindi,sans-serif;font-size:11pt;line-height:1.5}p{margin:10px 0}table{border-collapse:collapse;width:100%}td,th{border:1px solid black;padding:7px;font-family:sans-serif}"
    with pymupdf.open() as document:
        page=document.new_page(width=595,height=842)
        spare,scale=page.insert_htmlbox(pymupdf.Rect(40,35,555,800),html,css=css,archive=pymupdf.Archive(str(FONT.parent)))
        if spare<0 or scale<.95: raise ValueError('Synthetic fixture did not fit legibly')
        return document.tobytes()


def create_sec138_cheque_bounce_pdf():
    stream=BytesIO(); page=canvas.Canvas(stream)
    page.setFont('Helvetica',12)
    lines=['FICTIONAL OCR BENCHMARK - NOT A LEGAL NOTICE','CHAMBERS OF A FICTIONAL ADVOCATE','Date: 18/10/2026','STATUTORY NOTICE UNDER SECTION 138 OF THE NEGOTIABLE INSTRUMENTS ACT','Cheque Principal: INR 3,50,000','The cheque was returned with endorsement: Insufficient Funds.','Pay within 15 days from receipt of this notice.','Criminal prosecution and imprisonment are mentioned in the original.']
    for i,line in enumerate(lines): page.drawString(35,800-i*35,line)
    page.save(); return stream.getvalue()

def create_quishing_scam_notice_pdf(qr_only=False):
    stream=BytesIO(); page=canvas.Canvas(stream); page.setFont('Helvetica',12)
    page.drawString(40,800,'FICTIONAL SCAM OCR BENCHMARK')
    if not qr_only: page.drawString(40,760,'DIGITAL ARREST - pay gst.recovery.officer@okaxis within 2 hours')
    qr=QrCodeWidget('upi://pay?pa=gst.recovery.officer@okaxis&am=24999')
    x0,y0,x1,y1=qr.getBounds(); drawing=Drawing(180,180,transform=[180/(x1-x0),0,0,180/(y1-y0),0,0]); drawing.add(qr)
    renderPDF.draw(drawing,page,180,400); page.save(); return stream.getvalue()

def create_skewed_camera_photo_from_pdf(content,angle_deg=6):
    from app.engines.document_reader import _render_pdf
    image=cv2.imdecode(np.frombuffer(_render_pdf(content)[0],np.uint8),cv2.IMREAD_COLOR)
    h,w=image.shape[:2]; m=cv2.getRotationMatrix2D((w/2,h/2),angle_deg,1)
    image=cv2.warpAffine(image,m,(w,h),borderValue=(255,255,255))
    return cv2.imencode('.png',image)[1].tobytes()

if __name__=='__main__':
    folder=Path(__file__).parent/'generated-ocr'; folder.mkdir(parents=True,exist_ok=True)
    for name,data in [('bilingual-gst.pdf',create_bilingual_gst_drc01_pdf()),('section-138.pdf',create_sec138_cheque_bounce_pdf()),('scam-qr.pdf',create_quishing_scam_notice_pdf()),('skewed-bilingual.png',create_skewed_camera_photo_from_pdf(create_bilingual_gst_drc01_pdf()))]: (folder/name).write_bytes(data)
    print('Fictional bilingual/grid/skew/QR fixtures generated.')
