"""A hash of every data contract, so a helper never runs jobs against a portal with different formats."""
import hashlib
import json

from . import FrameworkAnalysisResult, HelperHeartbeat, JobUsage
from .assistant import AssistantReply, AssistantResult
from .cases import RegenerateResult
from .roles import AccessAnalysisResult, RoleEndpointResult
from .flows import DomainAnalysis, DomainModel, FlowAnalysisResult, FlowCaseSet, FlowPlan, FlowProgress, FlowReview, ProcessCatalog
from .scripts import ScriptEndpointResult, ScriptOutput
from .unit import CaseReview, CaseSet, ScenarioChecklist, UnitEndpointResult

_MODELS = (HelperHeartbeat, FrameworkAnalysisResult, ScenarioChecklist, CaseSet, CaseReview, UnitEndpointResult,
           ScriptOutput, ScriptEndpointResult, DomainModel, FlowPlan, FlowCaseSet, FlowReview, FlowAnalysisResult,
           RegenerateResult, FlowProgress, JobUsage, AccessAnalysisResult, RoleEndpointResult, DomainAnalysis, ProcessCatalog,
           AssistantReply, AssistantResult)

CONTRACT_FINGERPRINT = hashlib.sha256(
    json.dumps([m.model_json_schema() for m in _MODELS], sort_keys=True).encode()).hexdigest()[:16]
