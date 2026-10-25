import json,hashlib
from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED
from xml.sax.saxutils import escape
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from app.models import database

def brief_text(d):
    lines=['DOCKET.IN / PROFESSIONAL HAND-OFF BRIEF',f'Case: {d.id}',f'Status: {d.state.value} | Risk: {d.severity.value} ({d.deterministic_risk_score}/100)',f'Authenticity: {d.forensics.verdict.value}',d.forensics.verification_note]
    lines.extend([f'Case revision: {d.revision} | Playbook: {d.playbook_version}',f'Facts confirmed: {d.facts_confirmed} | User-recorded professional review: {d.professional_review}'])
    if d.source_sha256: lines.append('Original intake SHA-256: '+d.source_sha256)
    if d.submission_receipt: lines.extend(['User-recorded filing acknowledgement: '+d.submission_receipt,'Submitted on: '+(d.submitted_at or 'Confirm date'),'Receipt file: '+(d.submission_proof_name or 'Not attached'),'Filing and professional credentials have not been independently authenticated by Docket.'])
    if d.is_demo: lines.append('SAMPLE CASE — all verification signals are simulated.')
    if d.triage:
        t=d.triage
        lines.extend([t.issuing_authority,t.statutory_act_and_section,t.plain_english_summary,f'Exposure for review: INR {t.financial_demand_inr:,.2f}'])
    if d.limitation:
        l=d.limitation
        lines.extend([f'Issued: {l.date_of_issue} | Served: {l.date_of_service}',f'Raw expiry: {l.raw_expiry_date} | Planning deadline: {l.effective_legal_deadline}',l.calculation_note,l.holiday_reason or 'No office-calendar adjustment applied.'])
    if d.triage:
        lines.append('\nEVIDENCE INDEX')
        lines.extend(f'[{"x" if item.is_collected else " "}] {item.document_name}'+(f' — {item.attachment_name}' if item.attachment_name else '') for item in d.triage.required_documents)
        lines.extend(['\nDRAFT FOR REVIEW',d.draft_reply or d.triage.draft_reply_template])
    if not d.forensics.safe_to_process:
        lines.extend(['DO NOT PAY OR REPLY',*d.forensics.scam_flags])
    lines.extend(['\nREVIEW NOTES',*d.review_notes,'Prepared for professional review. No response has been submitted or sent.'])
    return '\n'.join(lines)

def make_pdf(text):
    buffer=BytesIO()
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='DocketBody',fontName='Helvetica',fontSize=9.5,leading=13,textColor=colors.HexColor('#263b30'),spaceAfter=1))
    styles.add(ParagraphStyle(name='DocketSection',fontName='Helvetica-Bold',fontSize=9,leading=13,textColor=colors.HexColor('#1b365d'),spaceBefore=9,spaceAfter=5))
    flow=[]
    for line in text.splitlines():
        # Core PDF font: ASCII transliteration preserves legibility without remote fonts.
        safe=line.replace('₹','INR ').replace('—',' - ').replace('·',' / ').encode('ascii','replace').decode()
        section=line in ('EVIDENCE INDEX','DRAFT FOR REVIEW','REVIEW NOTES','DO NOT PAY OR REPLY') or line.startswith('DOCKET.IN /')
        flow.append(Paragraph(escape(safe) or ' ',styles['DocketSection'] if section else styles['DocketBody']))
        if not line: flow.append(Spacer(1,1))
    def page_frame(canvas,doc):
        canvas.saveState()
        width,height=A4
        canvas.setStrokeColor(colors.HexColor('#dcd9ce'))
        canvas.line(45,height-49,width-45,height-49)
        canvas.setFillColor(colors.HexColor('#263b30'))
        canvas.setFont('Times-Bold',18)
        canvas.drawString(45,height-37,'docket.in')
        canvas.setFont('Helvetica',7)
        canvas.drawRightString(width-45,height-34,'THE SOVEREIGN DESK / FOR PROFESSIONAL REVIEW')
        canvas.line(45,44,width-45,44)
        canvas.setFont('Helvetica',7)
        canvas.setFillColor(colors.HexColor('#64735b'))
        canvas.drawString(45,30,'Planning support. Verify facts, authenticity and applicable deadlines before acting.')
        canvas.drawRightString(width-45,30,str(doc.page))
        canvas.restoreState()
    SimpleDocTemplate(buffer,pagesize=A4,title='Docket.in professional review brief',leftMargin=45,rightMargin=45,topMargin=65,bottomMargin=62).build(flow,onFirstPage=page_frame,onLaterPages=page_frame)
    return buffer.getvalue()

def make_zip(d):
    output=BytesIO()
    with ZipFile(output,'w',ZIP_DEFLATED) as archive:
        archive.writestr('professional-brief.pdf',make_pdf(brief_text(d)))
        archive.writestr('professional-brief.txt',brief_text(d))
        archive.writestr('dossier.json',d.model_dump_json(indent=2))
        archive.writestr('redacted-notice.txt',d.redacted_ocr_excerpt)
        archive.writestr('history.json',json.dumps(database.history(d.id),indent=2))
        manifest=[]
        for idx,(doc_id,name,content) in enumerate(database.evidence(d.id)):
            # Generate fixed archive paths; untrusted filenames never become paths.
            suffix=name.rsplit('.',1)[-1].lower() if '.' in name else 'bin'
            suffix=suffix if suffix in ('pdf','png','jpg','jpeg','txt','csv','xlsx') else 'bin'
            path=f'evidence/{idx+1:02d}-{doc_id}.{suffix}'
            archive.writestr(path,content)
            manifest.append({'document_id':doc_id,'original_name':name,'path':path,'sha256':hashlib.sha256(content).hexdigest()})
        archive.writestr('evidence/index.json',json.dumps(manifest,indent=2))
    return output.getvalue()
