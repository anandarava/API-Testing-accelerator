"""The project assistant: what it answers, which actions it may propose, and flows it drafts on request."""
from typing import Literal

from pydantic import Field

from . import Strict
from .flows import FlowCaseDraft, FlowOutline

ASSISTANT_KIND = 'assistant.message'
CASE_CODE = r'^TC-\d{4,}$'
Page = Literal['apis', 'unit', 'flows', 'roles', 'scripts', 'configuration', 'activity', 'members']


class AssistantAction(Strict):
    """An action the assistant proposes. Nothing happens until the user confirms it in the portal."""
    kind: Literal['review', 'regenerate', 'fill_gaps', 'export', 'open'] = Field(description=(
        'review: change the review status of caseCodes; regenerate: rewrite ONE case (caseCodes[0]) with instruction; '
        'fill_gaps: add flows for everything the flows do not cover yet, keeping existing flows; export: download cases; '
        'open: go to a page'))
    title: str = Field(min_length=3, max_length=120, description='What the action does, e.g. "Approve 4 flows"')
    caseCodes: list[str] = Field(default_factory=list, max_length=200)
    reviewAction: Literal['approve', 'needs_changes', 'reject', 'reopen'] | None = None
    comment: str = Field(default='', max_length=1000, description='Required for needs_changes and reject')
    instruction: str = Field(default='', max_length=1000, description='For regenerate: what to change')
    exportFormat: Literal['xlsx', 'csv'] | None = None
    exportStatus: Literal['all', 'approved'] | None = None
    module: Literal['unit', 'flow', 'role', 'all'] | None = None
    page: Page | None = None


class FlowRequest(Strict):
    """A flow the user says is missing; the helper designs, checks and writes it as a draft."""
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=10, max_length=2000, description='The journey in business terms: steps, data and expected outcome')


class AssistantReply(Strict):
    answer: str = Field(max_length=6000, description='The answer in short paragraphs or "- " lists; cite cases by code (TC-0123)')
    caseCodes: list[str] = Field(default_factory=list, max_length=60, description='Codes of the cases the answer is about')
    actions: list[AssistantAction] = Field(default_factory=list, max_length=4)
    flowRequests: list[FlowRequest] = Field(default_factory=list, max_length=3)
    followUps: list[str] = Field(default_factory=list, max_length=3, description='Short questions the user may ask next')


class FlowDraft(Strict):
    outline: FlowOutline
    flow: FlowCaseDraft
    area: str = Field(default='', max_length=120)


class AssistantResult(Strict):
    reply: AssistantReply
    drafts: list[FlowDraft] = Field(default_factory=list, max_length=6)
    draftError: str = Field(default='', max_length=600)
