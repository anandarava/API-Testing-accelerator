"""Structured outputs for Playwright script generation."""
from typing import Literal

from pydantic import Field

from . import Strict


class ScriptFile(Strict):
    path: str = Field(min_length=4, max_length=300, description='Path relative to the framework root, e.g. tests/api/pets-create.spec.ts')
    content: str = Field(min_length=20, max_length=400_000, description='The complete TypeScript file')
    caseCodes: list[str] = Field(min_length=1, description='Test case codes (TC-0001, ...) implemented in this file')


class ScriptOutput(Strict):
    file: ScriptFile
    envVariables: list[str] = Field(default_factory=list, max_length=40, description='Environment variables the tests need')
    notes: str = Field(default='', max_length=3000, description='Anything the QA must know: assumptions, new env variables, gaps')


class CheckResult(Strict):
    name: Literal['typecheck', 'lint', 'discovery']
    status: Literal['passed', 'failed', 'skipped']
    detail: str = Field(default='', max_length=500)
    output: str = Field(default='', max_length=8000)


class ScriptEndpointResult(Strict):
    """Sent by the helper after each endpoint's spec file is written and checked."""
    endpointId: str
    path: str = ''
    content: str = Field(default='', max_length=400_000)
    sha256: str = ''
    diff: str = Field(default='', max_length=400_000)
    caseIds: list[str] = Field(default_factory=list)
    checks: list[CheckResult] = Field(default_factory=list)
    fixRounds: int = 0
    envVariables: list[str] = Field(default_factory=list)
    notes: str = ''
    error: str = ''
