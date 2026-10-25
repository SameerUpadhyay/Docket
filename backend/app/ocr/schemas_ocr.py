from enum import Enum
from decimal import Decimal
from pydantic import BaseModel,Field,ConfigDict,field_validator

class StrictModel(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
class NoticeDomain(str,Enum):
    GST_NOTICE='GST_NOTICE'
    INCOME_TAX_NOTICE='INCOME_TAX_NOTICE'
    LABOUR_EPFO_ESIC='LABOUR_EPFO_ESIC'
    CHEQUE_BOUNCE_SEC138='CHEQUE_BOUNCE_SEC138'
    MINISTRY_CORPORATE_AFFAIRS='MINISTRY_CORPORATE_AFFAIRS'
    FSSAI_OR_MUNICIPAL='FSSAI_OR_MUNICIPAL'
    PRIVATE_LEGAL_NOTICE='PRIVATE_LEGAL_NOTICE'
    SUSPECTED_SCAM='SUSPECTED_SCAM'
    UNCLASSIFIED='UNCLASSIFIED'
class TriageUrgency(str,Enum):
    GREEN='GREEN'
    AMBER='AMBER'
    RED='RED'
    PHISHING_LOCKOUT='PHISHING_LOCKOUT'
class BoundingBoxHighlight(StrictModel):
    label:str
    extracted_value:str
    page_number:int=Field(ge=1)
    box_2d:tuple[int,int,int,int]
    provenance:str='source-text'
    @field_validator('box_2d')
    @classmethod
    def valid_box(cls,b):
        if not (0<=b[0]<b[2]<=1000 and 0<=b[1]<b[3]<=1000): raise ValueError('Invalid source bounding box')
        return b
class TaxTableRow(StrictModel):
    tax_head:str
    tax_or_principal_inr:Decimal|None=Field(default=None,ge=0)
    interest_inr:Decimal|None=Field(default=None,ge=0)
    penalty_inr:Decimal|None=Field(default=None,ge=0)
    late_fee_inr:Decimal|None=Field(default=None,ge=0)
    row_total_inr:Decimal|None=Field(default=None,ge=0)
    page_number:int=1
    provenance:str='source-grid'
class DeterministicAnchors(StrictModel):
    din_numbers:list[str]=Field(default_factory=list)
    gstin_numbers:list[str]=Field(default_factory=list)
    pan_numbers:list[str]=Field(default_factory=list)
    sections_cited:list[str]=Field(default_factory=list)
    dates_detected_iso:list[str]=Field(default_factory=list)
    qr_payloads:list[str]=Field(default_factory=list)
    upi_ids_detected:list[str]=Field(default_factory=list)
    devanagari_chars_present:bool=False
class VisionOcrStructuredOutput(StrictModel):
    detected_languages:list[str]
    notice_domain:NoticeDomain
    specific_form_code:str
    issuing_authority_name:str|None=None
    issuing_authority_location:str|None=None
    din_or_reference_id:str|None=None
    date_of_issue_iso:str|None=None
    response_window_days:int|None=Field(default=None,ge=1,le=365)
    explicit_due_date_iso:str|None=None
    statutory_sections_invoked:list[str]=Field(default_factory=list)
    core_allegation_english:str
    core_allegation_hindi:str
    tax_breakdown_table:list[TaxTableRow]=Field(default_factory=list)
    total_demand_inr:Decimal|None=Field(default=None,ge=0)
    threatens_bank_attachment_or_eway_block:bool=False
    threatens_criminal_prosecution:bool=False
    recommended_action_tier:str='PROFESSIONAL_REVIEW'
    required_documents_checklist:list[str]=Field(default_factory=list)
    draft_reply_skeleton:str='[PROFESSIONAL_REVIEW_REQUIRED]'
    full_markdown_transcript:str
    key_highlights:list[BoundingBoxHighlight]=Field(default_factory=list)
class CompleteOcrTriagePayload(StrictModel):
    document_id:str
    filename:str
    page_count:int
    extraction_engine_used:str
    image_quality_score:float|None=None
    deskew_angle_applied:float=0
    table_math_verified:bool|None=None
    table_math_discrepancy_note:str|None=None
    urgency:TriageUrgency
    deterministic_anchors:DeterministicAnchors
    structured_triage:VisionOcrStructuredOutput
    processing_latency_ms:int
    review_required:bool=True
    warnings:list[str]=Field(default_factory=list)
    pages:list[dict]=Field(default_factory=list)
