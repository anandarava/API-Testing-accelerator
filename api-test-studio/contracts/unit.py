"""Structured outputs of the unit test case agents."""
from typing import Any, Literal

from pydantic import Field

from . import Strict

Category = Literal['positive', 'required', 'type', 'boundary', 'format', 'enum', 'path_params', 'query_params',
                   'headers', 'auth', 'business', 'contract', 'security', 'idempotency', 'pagination', 'error_handling']
Priority = Literal['P1', 'P2', 'P3']
AuthMode = Literal['valid', 'none', 'invalid', 'expired', 'insufficient']


class Scenario(Strict):
    key: str = Field(pattern=r'^S\d{2,3}$', description='S01, S02, ... unique within the checklist')
    title: str = Field(min_length=3, max_length=200, description='What is tested, e.g. "Reject name longer than 50 characters"')
    category: Category
    condition: str = Field(max_length=500, description='The single input or state this scenario varies')
    expectedStatus: int | None = Field(ge=100, le=599, description='Documented status code; null only when the contract does not say')
    covers: list[str] = Field(default_factory=list, description='Ids of the coverage requirements this scenario satisfies')
    source: str = Field(max_length=300, description='The part of the contract this scenario comes from')
    priority: Priority
    needsConfirmation: bool = False
    confirmationNote: str = Field(default='', max_length=500)


class ScenarioChecklist(Strict):
    scenarios: list[Scenario] = Field(min_length=1, max_length=150)


class RequestSpec(Strict):
    auth: AuthMode = 'valid'
    pathParams: dict[str, Any] = Field(default_factory=dict)
    query: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = None
    bodyNote: str = Field(default='', max_length=500, description='Explain generated values, e.g. "name is 51 characters"')


class BodyCheck(Strict):
    path: str = Field(max_length=200, description='JSON path such as $.id or $.items[0].name')
    check: Literal['exists', 'not_exists', 'equals', 'not_equals', 'contains', 'type', 'matches_request',
                   'matches_pattern', 'one_of', 'length', 'greater_than', 'less_than'] = Field(description=(
        'equals/not_equals: value; contains: substring or array item; type: "string"|"number"|"integer"|"boolean"|"array"|"object"|"null"; '
        'matches_request: value is the request JSON path it must echo, e.g. "$.name"; matches_pattern: regular expression; '
        'one_of: array of allowed values; length: exact length of a string or array; greater_than/less_than: number'))
    value: Any = None


class Expected(Strict):
    status: int | None = Field(ge=100, le=599)
    responseSchema: Literal['success', 'error', 'none'] = Field(
        description='Validate the body against the documented success schema, the documented error schema, or not at all')
    bodyChecks: list[BodyCheck] = Field(default_factory=list, max_length=30)
    headers: dict[str, str] = Field(default_factory=dict)
    notes: str = Field(default='', max_length=1000)


class TestCaseDraft(Strict):
    scenarioKey: str = Field(pattern=r'^S\d{2,3}$')
    title: str = Field(min_length=3, max_length=200)
    objective: str = Field(max_length=1000)
    category: Category
    priority: Priority
    preconditions: list[str] = Field(default_factory=list, max_length=20)
    request: RequestSpec
    expected: Expected
    testData: str = Field(default='', max_length=1500, description='Data setup and how special values are produced')
    cleanup: list[str] = Field(default_factory=list, max_length=10)
    needsConfirmation: bool = False
    confirmationNote: str = Field(default='', max_length=500)


class CaseSet(Strict):
    cases: list[TestCaseDraft] = Field(min_length=1, max_length=150)


class ReviewFinding(Strict):
    scenarioKey: str = Field(description='Scenario key the finding is about, or "checklist" for missing coverage')
    severity: Literal['blocker', 'major', 'minor']
    issue: str = Field(max_length=600)
    suggestion: str = Field(default='', max_length=600)


class CaseReview(Strict):
    verdict: Literal['ready', 'needs_attention']
    summary: str = Field(max_length=800)
    findings: list[ReviewFinding] = Field(default_factory=list, max_length=60)


class UnitEndpointResult(Strict):
    """Sent by the helper after each endpoint finishes."""
    endpointId: str
    checklist: list[Scenario] = Field(default_factory=list)
    cases: list[TestCaseDraft] = Field(default_factory=list)
    review: CaseReview | None = None
    rounds: int = 1
    error: str = ''
