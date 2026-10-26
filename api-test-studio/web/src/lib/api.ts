export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const isForm = body instanceof FormData;
  const response = await fetch('/api' + path, {
    method,
    credentials: 'same-origin',
    headers: body === undefined || isForm ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const detail = data?.detail;
    throw new ApiError(response.status, typeof detail === 'string' ? detail : 'Something went wrong. Please try again.');
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, body),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, body),
  delete: <T>(path: string) => request<T>('DELETE', path),
  upload: <T>(path: string, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return request<T>('POST', path, form);
  },
};

// --- Types returned by the server ---------------------------------------------

export type Role = 'lead' | 'employee';

export interface User { id: string; name: string; email: string }

export interface ProjectCard {
  id: string;
  name: string;
  description: string;
  role: Role;
  createdAt: number;
  updatedAt: number;
  memberCount: number;
  spec: { title: string; version: number; apiVersion: string; endpointCount: number } | null;
}

export interface ProjectDetail extends ProjectCard {
  setup: { specUploaded: boolean; helperConnected: boolean; frameworkPathSet: boolean; frameworkProfile: 'missing' | 'draft' | 'confirmed' };
}

export interface Member { userId: string; name: string; email: string; role: Role; addedAt: number }

export interface ActivityItem { id: string; action: string; summary: string; actorName: string; createdAt: number }

export interface ClaudeStatus { installed: boolean; version: string; loggedIn: boolean; email: string; subscriptionType: string; error: string }
/** The helper's own OpenAI-compatible AI server (from its .env file). */
export interface LocalLlmStatus { configured: boolean; reachable: boolean; server: string; models: string[]; error: string }

export interface ModelOption { id: string; label: string; family: string }
export interface ModelPreferences { claudeModel: string; lastModels: string[]; lastUsedAt: number | null; options: ModelOption[] }

export interface HelperState {
  model: ModelPreferences;
  paired: boolean;
  connected: boolean;
  lastSeen: number | null;
  hostname: string;
  helperVersion: string;
  claude: ClaudeStatus | null;
  local: LocalLlmStatus | null;
}

export interface Spec {
  id: string;
  version: number;
  filename: string;
  format: string;
  title: string;
  apiVersion: string;
  description: string;
  servers: string[];
  securitySchemes: Record<string, Record<string, unknown>>;
  warnings: string[];
  changes: { added?: string[]; removed?: string[]; changed?: string[] };
  endpointCount: number;
  isCurrent: boolean;
  uploadedBy: string | null;
  createdAt: number;
}

export interface EndpointSummary { id: string; operationId: string; method: string; path: string; summary: string; tags: string[]; deprecated: boolean }

export type Schema = Record<string, any>;

export interface Parameter { name: string; in: string; required: boolean; description: string; deprecated: boolean; schema: Schema; example: unknown }

export interface EndpointDetail extends EndpointSummary {
  description: string;
  parameters: Parameter[];
  requestBody: { required: boolean; description: string; mediaType: string | null; contentTypes: string[]; schema: Schema; example: unknown } | null;
  responses: Record<string, { description: string; mediaType: string | null; schema: Schema; example: unknown; headers: string[] }>;
  security: Record<string, string[]>[];
}

export interface FlowGroupProgress {
  name: string;
  status: 'waiting' | 'working' | 'done' | 'failed';
  step: string;
  flows: number;
  startedAt?: number | null;
  finishedAt?: number | null;
}

/** Structured progress of a flow generation job, sent by the Local Helper. */
export interface FlowProgress {
  stage: 'analyze' | 'design' | 'coverage' | 'done';
  operations: number;
  entities?: number | null;
  rules?: number | null;
  areas?: number | null;
  parallel: number;
  groups: FlowGroupProgress[];
  savedFlows: number;
  gapFlows?: number | null;
  stageStartedAt: Partial<Record<FlowProgress['stage'], number>>;
}

/** Claude usage of one job, summed over its calls. */
export interface JobUsage { calls: number; inputTokens: number; cacheReadTokens: number; cacheWriteTokens: number; outputTokens: number; costUsd: number }

export interface Job {
  id: string;
  projectId: string;
  kind: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';
  requestedBy: string;
  requestedByName: string | null;
  progress: { message?: string; percent?: number | null; models?: string[]; detail?: FlowProgress; usage?: JobUsage };
  usage?: JobUsage | null;
  model: string | null;
  models: string[];
  error: string;
  createdAt: number;
  startedAt: number | null;
  finishedAt: number | null;
}

export interface NamedFile { name: string; file: string; description: string }

export interface FrameworkProfile {
  summary: string;
  testDirectory: string;
  testFilePattern: string;
  fileNaming: string;
  imports: { purpose: string; statement: string }[];
  httpClient: { style: 'playwright-request' | 'custom-client' | 'other'; description: string; location: string; exampleUsage: string };
  fixtures: NamedFile[];
  authentication: { approach: string; details: string; envVariables: string[] };
  baseUrl: { source: string; envVariable: string };
  assertions: { style: string; helpers: NamedFile[] };
  testData: { approach: string; location: string };
  environmentVariables: string[];
  conventions: string[];
  exampleTests: { file: string; why: string }[];
  warnings: string[];
}

export interface FrameworkScan {
  playwrightVersion: string;
  typescriptVersion: string;
  configFiles: string[];
  specFileCount: number;
  sampleSpecFiles: string[];
  scripts: Record<string, string>;
}

export interface FrameworkView {
  myPath: string;
  profile: FrameworkProfile | null;
  scan: FrameworkScan | null;
  status: 'missing' | 'draft' | 'confirmed';
  revision: number;
  updatedBy: string | null;
  updatedAt: number | null;
  latestJob: Job | null;
}

// --- Unit test cases ------------------------------------------------------------

export type CaseStatus = 'in_review' | 'approved' | 'needs_changes' | 'rejected';
export type Priority = 'P1' | 'P2' | 'P3';
export type AuthMode = 'valid' | 'none' | 'invalid' | 'expired' | 'insufficient';

export interface CoverageSummary { total: number; covered: number; gaps: number; outdated: boolean; error: string; generatedAt: number; verdict: 'ready' | 'needs_attention' | null }

export interface UnitEndpointRow {
  id: string;
  method: string;
  path: string;
  summary: string;
  tags: string[];
  cases: Record<CaseStatus, number>;
  caseCount: number;
  coverage: CoverageSummary | null;
}

export interface UnitOverview { endpoints: UnitEndpointRow[]; job: Job | null; totals: Record<CaseStatus, number> }

export interface Finding { scenarioKey: string; severity: 'blocker' | 'major' | 'minor'; issue: string; suggestion: string }

export interface RequestSpec { auth: AuthMode; pathParams: Record<string, unknown>; query: Record<string, unknown>; headers: Record<string, string>; body: unknown; bodyNote: string }

export interface BodyCheck { path: string; check: string; value: unknown }

export interface ExpectedResult { status: number | null; responseSchema: 'success' | 'error' | 'none'; bodyChecks: BodyCheck[]; headers: Record<string, string>; notes: string }

export interface TestCase {
  id: string;
  code: string;
  module: 'unit' | 'flow' | 'role';
  method: string;
  path: string;
  scenarioKey: string;
  title: string;
  category: string;
  priority: Priority;
  status: CaseStatus;
  needsConfirmation: boolean;
  content: {
    objective: string;
    preconditions: string[];
    request: RequestSpec;
    expected: ExpectedResult;
    testData: string;
    cleanup: string[];
    condition?: string;
    covers?: string[];
    source?: string;
    confirmationNote: string;
    /** Role cases: the roles the case runs as, which user, and how a refusal is proven harmless. */
    roles?: string[];
    userSlot?: 'first' | 'second';
    verifyUnchanged?: string;
  };
  findings: Finding[];
  reviewComment: string;
  revision: number;
  createdBy: string | null;
  createdAt: number;
  updatedBy: string | null;
  updatedAt: number;
  reviewedBy: string | null;
  reviewedAt: number | null;
  outdated: boolean;
  script: 'current' | 'outdated' | null;
}

export interface Requirement { id: string; category: string; description: string; source: string; covered: boolean; scenarios: string[] }

export interface UnitEndpointDetail {
  endpoint: { id: string; method: string; path: string; summary: string; operationId: string };
  coverage: CoverageSummary | null;
  requirements: Requirement[];
  review: { verdict: 'ready' | 'needs_attention'; summary: string; findings: Finding[] } | null;
  generatedBy: string | null;
  cases: TestCase[];
  regenerating: string[];
}

// --- Scripts -------------------------------------------------------------------------

export type ScriptState = 'not_generated' | 'up_to_date' | 'needs_update' | 'checks_failed' | 'failed';

export interface CheckSummary { name: 'typecheck' | 'lint' | 'discovery'; status: 'passed' | 'failed' | 'skipped'; detail: string }

export interface ScriptSummary {
  state: ScriptState;
  approved: number;
  scripted: number;
  changed: number;
  new: number;
  removed: number;
  checks: CheckSummary[];
  filePath: string;
  error: string;
  generatedAt: number | null;
}

export interface ScriptRow extends ScriptSummary { id: string; method: string; path: string; summary: string; generatedBy: string | null }

export interface ScriptsOverview { job: Job | null; profileStatus: 'missing' | 'draft' | 'confirmed'; frameworkPathSet: boolean; endpoints: ScriptRow[]; flows: FlowScriptRow[]; roleEndpoints: ScriptRow[] }

export interface ScriptDetail extends ScriptSummary {
  endpoint: { id: string; method: string; path: string; summary: string };
  cases: { id: string; code: string; title: string; state: 'current' | 'changed' | 'new' }[];
  content: string;
  diff: string;
  checksFull: (CheckSummary & { output: string })[];
  envVariables: string[];
  notes: string;
  fixRounds: number;
  generatedBy: string | null;
}

// --- Flow test cases -----------------------------------------------------------------

export interface FlowStepData {
  key: string;
  operationId: string;
  purpose: string;
  request: RequestSpec;
  expected: ExpectedResult;
  captures: { name: string; path: string }[];
}

export interface FlowContent {
  objective: string;
  preconditions: string[];
  steps: FlowStepData[];
  testData: string;
  cleanup: string[];
  goal: string;
  covers: string[];
  confirmationNote: string;
  operations: string[];
  area?: string;
}

export type FlowCase = Omit<TestCase, 'content'> & { content: FlowContent };

export interface DomainModel {
  summary: string;
  entities: { name: string; description: string; identifier: string; operations: string[]; states: string[]; lockedStates?: string[] }[];
  relationships: string[];
  transitions: { entity: string; fromState: string; toState: string; operationId: string; condition: string }[];
  businessRules: { key: string; rule: string; source: string; operations: string[]; kind?: string; needsSupport?: string }[];
  sideEffects?: { operationId: string; effect: string; verifyWith: string }[];
  areas?: { name: string; description: string; operations: string[] }[];
  assumptions: string[];
}

export interface AccessRow {
  operationId: string;
  allowed: string[];
  own: string[];
  denied: string[];
  unknown: string[];
  evidence: string;
  source: string;
  editedBy?: string;
}

export interface AccessModel {
  summary: string;
  roles: { name: string; description: string; users: number; source: string }[];
  operations: AccessRow[];
  rules: { rule: string; kind: string; operations: string[]; roles: string[]; source: string }[];
  systemCallers: string[];
  missingFromFile: string[];
  questions: string[];
}

export interface RoleCoverage { total: number; covered: number; error: string; generatedAt: number; outdated: boolean; verdict?: string }

export interface RolesOverview {
  document: { filename: string; size: number; uploadedAt: number; uploadedBy: string | null } | null;
  analysis: { model: AccessModel; generatedAt: number; generatedBy: string | null; editedAt: number | null; editedBy: string | null;
    outdated: boolean; ready: boolean } | null;
  credentials: { role: string; prefix: string; users: number }[];
  analyzeJob: Job | null;
  job: Job | null;
  endpoints: { id: string; method: string; path: string; summary: string; tags: string[]; operationId: string; access: AccessRow | null;
    cases: Record<CaseStatus, number>; caseCount: number; roles: string[]; coverage: RoleCoverage | null }[];
  totals: Record<CaseStatus, number>;
}

export interface RoleEndpointDetail {
  endpoint: { id: string; method: string; path: string; summary: string; operationId: string };
  access: AccessRow | null;
  rules: AccessModel['rules'];
  coverage: RoleCoverage | null;
  requirements: { id: string; category: string; role: string; description: string; covered: boolean; cases: string[] }[];
  review: UnitEndpointDetail['review'];
  cases: TestCase[];
  regenerating: string[];
}

export interface FlowsOverview {
  job: Job | null;
  analysis: {
    domain: DomainModel;
    review: { verdict: 'ready' | 'needs_attention'; summary: string; findings: { flowKey: string; severity: string; issue: string; suggestion: string }[] } | null;
    requirements: { id: string; category: string; description: string; covered: boolean }[];
    covered: number;
    total: number;
    generatedAt: number;
    generatedBy: string | null;
    outdated: boolean;
  } | null;
  /** Set when the last design stopped part-way and can continue without redoing finished areas. */
  resume: { doneGroups: number; totalGroups: number; flows: number } | null;
  operations: Record<string, { method: string; path: string; summary?: string }>;
  totals: Record<CaseStatus, number>;
  flows: FlowCase[];
  regenerating: string[];
}

export interface FlowScriptRow extends ScriptSummary { id: string; code: string; title: string; steps: number; generatedBy: string | null }
