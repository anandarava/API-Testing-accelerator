"""Data contracts shared by the portal server and the Local Helper."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

VERSION = '0.1.0'

# Claude models a user can choose: (id passed to --model, label, family).
# A family alias ('opus', ...) always resolves to that family's newest model; a full id pins one version.
# 'default' sends no --model flag, so the account's default model is used. Retired models are left out.
CLAUDE_MODEL_CATALOG = (
    ('default', 'Account default', ''),
    ('fable', 'Latest Fable', 'Fable'),
    ('claude-fable-5-1', 'Fable 5.1', 'Fable'),
    ('claude-fable-5', 'Fable 5', 'Fable'),
    ('opus', 'Latest Opus', 'Opus'),
    ('claude-opus-5-5', 'Opus 5.5', 'Opus'),
    ('claude-opus-5', 'Opus 5', 'Opus'),
    ('claude-opus-4-8', 'Opus 4.8', 'Opus'),
    ('claude-opus-4-7', 'Opus 4.7', 'Opus'),
    ('claude-opus-4-6', 'Opus 4.6', 'Opus'),
    ('claude-opus-4-5', 'Opus 4.5', 'Opus'),
    ('sonnet', 'Latest Sonnet', 'Sonnet'),
    ('claude-sonnet-5-5', 'Sonnet 5.5', 'Sonnet'),
    ('claude-sonnet-5', 'Sonnet 5', 'Sonnet'),
    ('claude-sonnet-4-6', 'Sonnet 4.6', 'Sonnet'),
    ('claude-sonnet-4-5', 'Sonnet 4.5', 'Sonnet'),
    ('haiku', 'Latest Haiku', 'Haiku'),
    ('claude-haiku-5-5', 'Haiku 5.5', 'Haiku'),
    ('claude-haiku-4-5', 'Haiku 4.5', 'Haiku'),
)
CLAUDE_MODELS = tuple(model_id for model_id, _, _ in CLAUDE_MODEL_CATALOG)
# Any other full model id (for example a version released after this list was written).
CUSTOM_MODEL_PATTERN = r'claude-[a-z]+-[0-9]+(-[0-9]+)*'
# A model on the user's own OpenAI-compatible server (LiteLLM, Ollama), e.g. "local:qwen3.5:35b".
LOCAL_MODEL_PREFIX = 'local:'
LOCAL_MODEL_PATTERN = r'local:[A-Za-z0-9][A-Za-z0-9._:/-]{0,53}'


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class AgentUsage(Strict):
    """One agent's share of a job: Claude usage, failed calls, and how its answers fared in the code checks."""
    calls: int = Field(default=0, ge=0)
    inputTokens: int = Field(default=0, ge=0)
    cacheReadTokens: int = Field(default=0, ge=0)
    cacheWriteTokens: int = Field(default=0, ge=0)
    outputTokens: int = Field(default=0, ge=0)
    errors: int = Field(default=0, ge=0, description='Calls that failed (timeouts, unusable answers)')
    checked: int = Field(default=0, ge=0, description='Items the code checked (cases, flows, scenarios)')
    checkFailed: int = Field(default=0, ge=0, description='Items that failed the code check at first')


class JobUsage(Strict):
    """Claude usage of one job, summed over its calls from Claude Code's own report."""
    calls: int = Field(default=0, ge=0)
    inputTokens: int = Field(default=0, ge=0, description='Input tokens not read from the prompt cache')
    cacheReadTokens: int = Field(default=0, ge=0)
    cacheWriteTokens: int = Field(default=0, ge=0)
    outputTokens: int = Field(default=0, ge=0)
    costUsd: float = Field(default=0, ge=0, description='What the calls would cost at API prices')
    agents: dict[str, AgentUsage] = Field(default_factory=dict, description='Per agent')


# --- Local Helper status -------------------------------------------------

class ClaudeStatus(Strict):
    installed: bool
    version: str = ''
    loggedIn: bool = False
    email: str = ''
    subscriptionType: str = ''
    error: str = ''


class LocalLlmStatus(Strict):
    """The helper's local AI server, if one is set up. The address and key stay on the helper's computer."""
    configured: bool = False
    reachable: bool = False
    server: str = Field(default='', max_length=200, description='Host name of the server, without the key')
    models: list[str] = Field(default_factory=list, max_length=30, description='Chat models the key may use')
    error: str = Field(default='', max_length=300)


class HelperHeartbeat(Strict):
    hostname: str = Field(default='', max_length=200)
    helperVersion: str = Field(default='', max_length=40)
    claude: ClaudeStatus
    local: LocalLlmStatus = Field(default_factory=LocalLlmStatus)


# --- Framework profile (output of the framework-analyzer agent) ----------

class ImportStatement(Strict):
    purpose: str = Field(max_length=200, description='What the import provides, e.g. "test fixture with API clients"')
    statement: str = Field(max_length=500, description='Exact import line as used in existing tests')


class NamedFile(Strict):
    name: str = Field(max_length=200)
    file: str = Field(max_length=500, description='Path relative to the framework root')
    description: str = Field(max_length=1000)


class HttpClient(Strict):
    style: Literal['playwright-request', 'custom-client', 'other']
    description: str = Field(max_length=2000)
    location: str = Field(default='', max_length=500)
    exampleUsage: str = Field(default='', max_length=3000)


class Authentication(Strict):
    approach: str = Field(max_length=1000)
    details: str = Field(default='', max_length=3000)
    envVariables: list[str] = Field(default_factory=list, max_length=50)


class BaseUrlConfig(Strict):
    source: str = Field(max_length=1000)
    envVariable: str = Field(default='', max_length=200)


class Assertions(Strict):
    style: str = Field(max_length=1000)
    helpers: list[NamedFile] = Field(default_factory=list, max_length=50)


class TestDataApproach(Strict):
    approach: str = Field(max_length=2000)
    location: str = Field(default='', max_length=500)


class ExampleTest(Strict):
    file: str = Field(max_length=500)
    why: str = Field(max_length=1000)


class FrameworkProfile(Strict):
    summary: str = Field(max_length=3000, description='Two to four sentences describing the framework')
    testDirectory: str = Field(max_length=500, description='Folder where new API spec files should be created')
    testFilePattern: str = Field(max_length=300, description='Glob for API spec files, e.g. tests/api/**/*.spec.ts')
    fileNaming: str = Field(max_length=1000, description='How spec files are named')
    imports: list[ImportStatement] = Field(default_factory=list, max_length=50)
    httpClient: HttpClient
    fixtures: list[NamedFile] = Field(default_factory=list, max_length=50)
    authentication: Authentication
    baseUrl: BaseUrlConfig
    assertions: Assertions
    testData: TestDataApproach
    environmentVariables: list[str] = Field(default_factory=list, max_length=100)
    conventions: list[str] = Field(default_factory=list, max_length=60,
                                   description='Short rules new tests must follow')
    exampleTests: list[ExampleTest] = Field(default_factory=list, max_length=5)
    warnings: list[str] = Field(default_factory=list, max_length=30)


class FrameworkScan(Strict):
    """Deterministic facts gathered by the helper before Claude is called."""
    playwrightVersion: str = ''
    typescriptVersion: str = ''
    configFiles: list[str] = Field(default_factory=list)
    specFileCount: int = 0
    sampleSpecFiles: list[str] = Field(default_factory=list)
    scripts: dict[str, str] = Field(default_factory=dict)
    envExampleKeys: list[str] = Field(default_factory=list, description='Variable names from .env.example (values are never read)')


class FrameworkAnalysisResult(Strict):
    profile: FrameworkProfile
    scan: FrameworkScan


JOB_KINDS = ('framework.analyze', 'unit.generate', 'scripts.generate', 'flows.generate', 'case.regenerate', 'access.analyze',
             'roles.generate', 'assistant.message')
# Answered on the helper's own lane, so a long generation never blocks a question.
ASSISTANT_KINDS = ('assistant.message',)
