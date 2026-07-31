"""Provider-neutral market-data evidence contracts and deterministic selectors."""

from equity_analysis.evidence_foundation.contracts_v1 import (
    EvidenceCandidate,
    EvidenceLayer,
    EvidenceParentReference,
    EvidenceSelectionRequest,
    SecurityIdentity,
    UnifiedEvidenceContractViolation,
    applicability_for_company_type,
)
from equity_analysis.evidence_foundation.domain_contracts_v1 import EvidenceDomain
from equity_analysis.evidence_foundation.persistence_v1 import (
    EvidenceFoundationIntegrityConflict,
    EvidenceFoundationRepository,
    ModelApplicabilityRouting,
    PersistedEvidenceEnvelope,
    PersistedSelectorAggregate,
)
from equity_analysis.evidence_foundation.provider_adapter_v1 import (
    CanonicalEvidenceBatchV1,
    ProviderAdapterDescriptorV1,
    ProviderEvidenceAdapterV1,
    ProviderEvidenceRequestV1,
)
from equity_analysis.evidence_foundation.refresh_v1 import (
    EvidenceRefreshPlanV1,
    ProviderNeutralEvidenceRefreshCoordinatorV1,
    bind_daily_refresh_plan_v1,
)
from equity_analysis.evidence_foundation.selector_v1 import (
    EvidenceSelectionResult,
    select_evidence,
)

__all__ = [
    "EvidenceCandidate",
    "EvidenceDomain",
    "EvidenceLayer",
    "EvidenceParentReference",
    "EvidenceFoundationRepository",
    "EvidenceFoundationIntegrityConflict",
    "EvidenceSelectionRequest",
    "EvidenceSelectionResult",
    "EvidenceRefreshPlanV1",
    "ModelApplicabilityRouting",
    "CanonicalEvidenceBatchV1",
    "ProviderAdapterDescriptorV1",
    "ProviderEvidenceAdapterV1",
    "ProviderEvidenceRequestV1",
    "ProviderNeutralEvidenceRefreshCoordinatorV1",
    "SecurityIdentity",
    "PersistedEvidenceEnvelope",
    "PersistedSelectorAggregate",
    "UnifiedEvidenceContractViolation",
    "applicability_for_company_type",
    "bind_daily_refresh_plan_v1",
    "select_evidence",
]
