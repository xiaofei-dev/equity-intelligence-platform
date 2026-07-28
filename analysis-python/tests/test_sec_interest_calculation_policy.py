import json
from hashlib import sha256
from pathlib import Path

from equity_analysis.provider_validation.expansion_gate import canonical_hash
from equity_analysis.provider_validation.sec_interest_calculation_policy import (
    CONDITIONAL_INTEREST_CONCEPT,
    SEC_INTEREST_CALCULATION_PARSER_VERSION,
    calculation_neighborhood,
    evaluate_interest_calculation_evidence,
    parse_calculation_linkbase,
    select_calculation_document,
)

CALCULATION = b"""<?xml version="1.0"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
 xmlns:xlink="http://www.w3.org/1999/xlink">
 <link:calculationLink xlink:role="http://example/role/StatementOfOperations">
  <link:loc xlink:label="total"
   xlink:href="test.xsd#us-gaap_InterestExpense"/>
  <link:loc xlink:label="nonoperating"
   xlink:href="test.xsd#us-gaap_InterestExpenseNonoperating"/>
  <link:loc xlink:label="other"
   xlink:href="test.xsd#issuer_OtherInterestExpense"/>
  <link:calculationArc
   xlink:arcrole="http://www.xbrl.org/2003/arcrole/summation-item"
   xlink:from="total" xlink:to="nonoperating" weight="1" order="1"/>
  <link:calculationArc
   xlink:arcrole="http://www.xbrl.org/2003/arcrole/summation-item"
   xlink:from="total" xlink:to="other" weight="1" order="2"/>
 </link:calculationLink>
</link:linkbase>"""


def test_calculation_document_discovery_is_optional_and_deterministic() -> None:
    assert (
        select_calculation_document(
            {
                "directory": {
                    "item": [
                        {"name": "issuer_pre.xml"},
                        {"name": "issuer_cal.xml"},
                    ]
                }
            }
        )
        == "issuer_cal.xml"
    )
    assert select_calculation_document({"directory": {"item": []}}) is None


def test_parser_preserves_network_role_direction_and_weight() -> None:
    parsed = parse_calculation_linkbase(CALCULATION)
    assert parsed["parserVersion"] == SEC_INTEREST_CALCULATION_PARSER_VERSION
    assert parsed["dtsCompletenessProven"] is False
    neighborhood = calculation_neighborhood(
        parsed,
        CONDITIONAL_INTEREST_CONCEPT,
    )
    assert neighborhood == [
        {
            "statementRole": "http://example/role/StatementOfOperations",
            "direction": "COMPONENT_TO_TOTAL",
            "otherConcept": "us-gaap:InterestExpense",
            "weight": "1",
        }
    ]


def test_broader_interest_total_is_positive_rejection_evidence() -> None:
    result = evaluate_interest_calculation_evidence(
        {"0000000000-26-000001": parse_calculation_linkbase(CALCULATION)},
        statement_roles_by_accession={},
        comparable_contexts_proven=True,
        complete_accession_set=True,
    )
    assert result["status"] == "REJECT"
    assert result["automaticScopeAuthorization"] is False
    assert result["reasonCodes"] == [
        "POSITIVE_CALCULATION_SCOPE_CONTRADICTION"
    ]


def test_missing_or_noncontradictory_calculation_never_auto_passes() -> None:
    missing = evaluate_interest_calculation_evidence(
        {},
        statement_roles_by_accession={},
        comparable_contexts_proven=False,
        complete_accession_set=False,
    )
    assert missing["status"] == "PARTIAL"
    assert missing["reasonCodes"] == [
        "CALCULATION_LINKBASE_MISSING_OR_NOT_COLLECTED"
    ]
    assert missing["automaticScopeAuthorization"] is False

    empty = parse_calculation_linkbase(
        b"""<link:linkbase
         xmlns:link="http://www.xbrl.org/2003/linkbase"/>"""
    )
    partial = evaluate_interest_calculation_evidence(
        {"0000000000-26-000001": empty},
        statement_roles_by_accession={},
        comparable_contexts_proven=True,
        complete_accession_set=True,
    )
    assert partial["status"] == "PARTIAL"
    assert partial["automaticScopeAuthorization"] is False


def test_equal_values_are_not_an_input_to_calculation_authorization() -> None:
    result = evaluate_interest_calculation_evidence(
        {},
        statement_roles_by_accession={},
        comparable_contexts_proven=True,
        complete_accession_set=True,
    )
    assert "value" not in str(result).lower()
    assert result["automaticScopeAuthorization"] is False


def test_machine_policy_freezes_no_network_preflight_and_source_hashes() -> None:
    root = Path(__file__).resolve().parents[2]
    path = (
        root
        / "docs/generated/"
        "objective-rating-v1-sec-interest-calculation-policy-v1.json"
    )
    artifact = json.loads(path.read_text(encoding="utf-8"))
    assert artifact["artifactContentHash"] == canonical_hash(
        {
            key: value
            for key, value in artifact.items()
            if key != "artifactContentHash"
        }
    )
    assert artifact["automaticPassAllowed"] is False
    assert artifact["preflight"]["accessionCount"] == 18
    assert artifact["preflight"]["physicalRequestsIfApproved"] == 18
    assert artifact["preflight"]["networkAccessed"] is False
    assert (
        artifact["preflight"]["executionDecision"]
        == "NOT_APPROVED_NO_AUTOMATIC_PASS_PATH"
    )
    for source_key in ("sourceCanary", "sourceEvidenceRun"):
        source = artifact[source_key]
        source_path = root / source["path"]
        assert sha256(source_path.read_bytes()).hexdigest().upper() == source[
            "fileSha256"
        ]
        source_payload = json.loads(source_path.read_text(encoding="utf-8"))
        assert source_payload["artifactContentHash"] == source["contentHash"]
