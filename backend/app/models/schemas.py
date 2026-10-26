from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field
from app.ocr.schemas_ocr import CompleteOcrTriagePayload

class NoticeState(str, Enum):
    NEW='NEW'
    TRIAGED='TRIAGED'
    PHISHING_QUARANTINED='PHISHING_QUARANTINED'
    DOCS_GATHERING='DOCS_GATHERING'
    DRAFT_READY='DRAFT_READY'
    CA_ESCALATED='CA_ESCALATED'
    SUBMITTED_CLOSED='SUBMITTED_CLOSED'

class SeverityTier(str, Enum):
    GREEN='GREEN'
    AMBER='AMBER'
    RED='RED'
    PHISHING_SCAM='PHISHING_SCAM'

class AuthenticityVerdict(str, Enum):
    VERIFIED_GOV='VERIFIED_GOV'
    PRIVATE_LEGAL_NOTICE='PRIVATE_LEGAL_NOTICE'
    SUSPICIOUS_UNVERIFIED='SUSPICIOUS_UNVERIFIED'
    PHISHING_SCAM='PHISHING_SCAM'

class ForensicCheckResult(BaseModel):
    verdict: AuthenticityVerdict
    fraud_risk_score: int = Field(ge=0,le=100)
    sender_email: str | None = None
    sender_domain: str | None = None
    dkim_passed: bool | None = None
    spf_passed: bool | None = None
    din_extracted: str | None = None
    din_format_valid: bool = False
    scam_flags: list[str] = Field(default_factory=list)
    safe_to_process: bool = True
    verification_note: str = 'Heuristic screening only. Verify independently on the issuing authority’s portal.'

class LimitationComputation(BaseModel):
    date_of_issue: str
    date_of_service: str
    statutory_window_days: int
    raw_expiry_date: str
    holiday_rollover_applied: bool
    holiday_reason: str | None = None
    effective_legal_deadline: str
    days_remaining: int
    next_watchdog_alert: str
    requires_review: bool = True
    calculation_note: str = 'Planning estimate. Confirm the prescribed period, service date and applicable office calendar.'

class RequiredDocumentItem(BaseModel):
    doc_id: str
    document_name: str
    why_needed: str
    source_hint: str
    is_collected: bool = False
    attachment_name: str | None = None

class LLMTriageExtraction(BaseModel):
    issuing_authority: str
    notice_type_title: str
    statutory_act_and_section: str
    plain_english_summary: str
    core_allegation_or_query: str
    financial_demand_inr: float = Field(ge=0)
    date_of_issue_iso: str | None = None
    response_window_days: int | None = Field(default=None,ge=1,le=365)
    has_criminal_or_arrest_clause: bool = False
    has_bank_freeze_or_eway_block_threat: bool = False
    recommended_professional: str
    professional_reason: str
    required_documents: list[RequiredDocumentItem]
    draft_reply_template: str
    vernacular_summary_hindi: str

class CompleteNoticeDossier(BaseModel):
    id: str
    ingested_at: str
    ingestion_channel: str
    state: NoticeState
    severity: SeverityTier
    deterministic_risk_score: int = Field(ge=0,le=100)
    forensics: ForensicCheckResult
    limitation: LimitationComputation | None = None
    triage: LLMTriageExtraction | None = None
    redacted_ocr_excerpt: str
    pii_tokens_redacted_count: int
    is_demo: bool = False
    analysis_mode: str = 'local-playbook'
    original_filename: str | None = None
    review_notes: list[str] = Field(default_factory=list)
    draft_reply: str | None = None
    facts_confirmed: bool = False
    professional_review: str = 'PENDING'
    submission_receipt: str | None = None
    submission_proof_name: str | None = None
    revision: int = 0
    submitted_at: str | None = None
    ocr_analysis: CompleteOcrTriagePayload | None = None
    ocr_report: dict = Field(default_factory=dict)
    source_sha256: str | None = None
    email_intake: dict = Field(default_factory=dict)
    playbook_version: str = '2026-10-25-unreviewed'

class ChecklistUpdate(BaseModel):
    is_collected: bool

class DraftUpdate(BaseModel):
    expected_revision: int | None = None
    draft_reply: str = Field(max_length=50000)

class StateUpdate(BaseModel):
    state: Literal['CA_ESCALATED','SUBMITTED_CLOSED']
