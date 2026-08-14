from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol


class ProducerViolation(ValueError):
    """Raised when a governed operand producer contract is not satisfied."""


@dataclass(frozen=True)
class ParentSlotContractV1:
    role_code: str
    domain: str
    field_code: str
    unit: str
    currency_rule: str
    fiscal_period: str
    period_identity: str
    period_start: str | None
    period_end: str

    def __post_init__(self) -> None:
        if self.currency_rule not in {"MATCH_OUTPUT", "NOT_APPLICABLE"}:
            raise ProducerViolation("PRODUCER_PARENT_CURRENCY_RULE_INVALID")


@dataclass(frozen=True)
class ProducerParentObservationV1:
    role_code: str
    evidence_id: str
    domain: str
    field_code: str
    unit: str
    currency: str | None
    fiscal_period: str
    period_start: str | None
    period_end: str
    value: Decimal


class OperandEvaluatorV1(Protocol):
    def __call__(self, parents: tuple[ProducerParentObservationV1, ...]) -> Decimal: ...


@dataclass(frozen=True)
class OperandProducerContractV1:
    operand_code: str
    source_kind: str
    contract_version: str
    evaluator_id: str
    governance_status: str
    parent_slots: tuple[ParentSlotContractV1, ...]
    output_semantics: str
    evaluator: OperandEvaluatorV1
    content_hash: str = ""

    def __post_init__(self) -> None:
        if self.governance_status != "TEST_ONLY":
            raise ProducerViolation("ONLY_TEST_ONLY_PRODUCERS_SUPPORTED_IN_V1")
        try:
            period_end = date.fromisoformat(self.parent_slots[0].period_end)
            for slot in self.parent_slots:
                if date.fromisoformat(slot.period_end) != period_end:
                    raise ProducerViolation("PRODUCER_PARENT_PERIOD_IDENTITY_DRIFT")
                if slot.period_start is not None and date.fromisoformat(
                    slot.period_start
                ) > period_end:
                    raise ProducerViolation("PRODUCER_PARENT_PERIOD_CHRONOLOGY_INVALID")
        except (IndexError, ValueError) as error:
            raise ProducerViolation("PRODUCER_PARENT_PERIOD_IDENTITY_INVALID") from error
        payload = {
            "operandCode": self.operand_code,
            "sourceKind": self.source_kind,
            "contractVersion": self.contract_version,
            "evaluatorId": self.evaluator_id,
            "governanceStatus": self.governance_status,
            "parentSlots": [slot.__dict__ for slot in self.parent_slots],
            "outputSemantics": self.output_semantics,
        }
        expected = "sha256:" + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if self.content_hash and self.content_hash != expected:
            raise ProducerViolation("PRODUCER_CONTRACT_HASH_DRIFT")
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected)

    def evaluate(self, parents: tuple[ProducerParentObservationV1, ...]) -> Decimal:
        if len(parents) != len(self.parent_slots):
            raise ProducerViolation("PRODUCER_PARENT_CARDINALITY_DRIFT")
        if len({parent.evidence_id for parent in parents}) != len(parents):
            raise ProducerViolation("DUPLICATE_PRODUCER_PARENT_EVIDENCE_ID")
        for slot, parent in zip(self.parent_slots, parents, strict=True):
            if (
                parent.role_code != slot.role_code
                or parent.domain != slot.domain
                or parent.field_code != slot.field_code
                or parent.unit != slot.unit
                or parent.fiscal_period != slot.fiscal_period
                or parent.period_start != slot.period_start
                or parent.period_end != slot.period_end
                or (slot.currency_rule == "MATCH_OUTPUT" and parent.currency is None)
                or (slot.currency_rule == "NOT_APPLICABLE" and parent.currency is not None)
            ):
                raise ProducerViolation("PRODUCER_PARENT_SEMANTICS_DRIFT")
        result = self.evaluator(parents)
        if not result.is_finite():
            raise ProducerViolation("PRODUCER_OUTPUT_NONFINITE")
        return result


class OperandProducerRegistryV1:
    def __init__(
        self,
        contracts: tuple[OperandProducerContractV1, ...] = (),
        *,
        allow_test_only: bool = False,
    ) -> None:
        if contracts and not allow_test_only:
            raise ProducerViolation("TEST_ONLY_PRODUCER_REGISTRY_REQUIRES_EXPLICIT_OPT_IN")
        by_operand = {contract.operand_code: contract for contract in contracts}
        if len(by_operand) != len(contracts):
            raise ProducerViolation("DUPLICATE_OPERAND_PRODUCER_CONTRACT")
        self._contracts = by_operand

    def get(self, operand_code: str) -> OperandProducerContractV1 | None:
        return self._contracts.get(operand_code)

    @property
    def contracts(self) -> tuple[OperandProducerContractV1, ...]:
        return tuple(self._contracts.values())


PRODUCTION_OPERAND_PRODUCERS_V1 = OperandProducerRegistryV1()
