from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any
from xml.etree import ElementTree

SEC_INTEREST_CALCULATION_PARSER_VERSION = (
    "sec-interest-calculation-linkbase-parser-v1.0.0"
)
SEC_INTEREST_CALCULATION_POLICY_VERSION = (
    "sec-interest-scope-continuity-calculation-policy-v1.0.0"
)
SUMMATION_ITEM_ARCROLE = (
    "http://www.xbrl.org/2003/arcrole/summation-item"
)

STRICT_INTEREST_CONCEPT = "us-gaap:InterestExpense"
CONDITIONAL_INTEREST_CONCEPT = "us-gaap:InterestExpenseNonoperating"
CONTRADICTORY_SCOPE_TOKENS = (
    "interestincome",
    "capitalizedinterest",
    "debtissuancecost",
    "debtexpense",
    "financingcost",
)


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def _concept_from_href(value: str) -> str:
    fragment = value.rsplit("#", 1)[-1]
    return fragment.replace("_", ":", 1)


def select_calculation_document(index_payload: dict[str, Any]) -> str | None:
    """Return the one issuer calculation linkbase, if the filing has one."""
    items = index_payload.get("directory", {}).get("item", ())
    matches = sorted(
        str(item["name"])
        for item in items
        if isinstance(item, dict)
        and item.get("name")
        and str(item["name"]).lower().endswith("_cal.xml")
    )
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError("SEC_FILING_CALCULATION_LINKBASE_NOT_UNIQUE")
    return matches[0]


def parse_calculation_linkbase(document: bytes) -> dict[str, Any]:
    """Parse filing-local calculation arcs without inferring DTS completeness."""
    root = ElementTree.fromstring(document)
    networks: list[dict[str, Any]] = []
    unsupported_arcroles: set[str] = set()
    for link in root.iter():
        if _local_name(link.tag) != "calculationLink":
            continue
        role = link.attrib.get(
            "{http://www.w3.org/1999/xlink}role",
            "",
        )
        locators = {
            element.attrib.get(
                "{http://www.w3.org/1999/xlink}label",
                "",
            ): _concept_from_href(
                element.attrib.get(
                    "{http://www.w3.org/1999/xlink}href",
                    "",
                )
            )
            for element in link
            if _local_name(element.tag) == "loc"
        }
        arcs = []
        for element in link:
            if _local_name(element.tag) != "calculationArc":
                continue
            arcrole = element.attrib.get(
                "{http://www.w3.org/1999/xlink}arcrole",
                "",
            )
            if arcrole != SUMMATION_ITEM_ARCROLE:
                unsupported_arcroles.add(arcrole)
                continue
            parent = locators.get(
                element.attrib.get(
                    "{http://www.w3.org/1999/xlink}from",
                    "",
                )
            )
            child = locators.get(
                element.attrib.get(
                    "{http://www.w3.org/1999/xlink}to",
                    "",
                )
            )
            if not parent or not child:
                raise ValueError("SEC_CALCULATION_ARC_LOCATOR_UNRESOLVED")
            try:
                weight = Decimal(element.attrib["weight"])
            except (KeyError, InvalidOperation) as error:
                raise ValueError("SEC_CALCULATION_WEIGHT_INVALID") from error
            if weight not in {Decimal("1"), Decimal("-1")}:
                raise ValueError("SEC_CALCULATION_WEIGHT_UNSUPPORTED")
            arcs.append(
                {
                    "arcrole": arcrole,
                    "parentConcept": parent,
                    "childConcept": child,
                    "weight": str(weight),
                    "order": element.attrib.get("order"),
                    "priority": element.attrib.get("priority", "0"),
                    "use": element.attrib.get(
                        "{http://www.w3.org/1999/xlink}use",
                        element.attrib.get("use", "optional"),
                    ),
                }
            )
        networks.append(
            {
                "statementRole": role,
                "arcs": sorted(
                    arcs,
                    key=lambda item: (
                        item["parentConcept"],
                        item["childConcept"],
                        item["order"] or "",
                    ),
                ),
            }
        )
    return {
        "parserVersion": SEC_INTEREST_CALCULATION_PARSER_VERSION,
        "networkCount": len(networks),
        "networks": sorted(
            networks,
            key=lambda item: item["statementRole"],
        ),
        "unsupportedArcroles": sorted(unsupported_arcroles),
        "dtsCompletenessProven": False,
    }


def _active_arcs(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    arcs = []
    for network in parsed["networks"]:
        for arc in network["arcs"]:
            if arc["use"] == "prohibited":
                continue
            arcs.append(
                {
                    **arc,
                    "statementRole": network["statementRole"],
                }
            )
    return arcs


def calculation_neighborhood(
    parsed: dict[str, Any],
    concept: str,
) -> list[dict[str, Any]]:
    """Return structural neighbors; this does not authorize economic equivalence."""
    result = []
    for arc in _active_arcs(parsed):
        if concept not in {arc["parentConcept"], arc["childConcept"]}:
            continue
        result.append(
            {
                "statementRole": arc["statementRole"],
                "direction": (
                    "TOTAL_TO_COMPONENT"
                    if arc["parentConcept"] == concept
                    else "COMPONENT_TO_TOTAL"
                ),
                "otherConcept": (
                    arc["childConcept"]
                    if arc["parentConcept"] == concept
                    else arc["parentConcept"]
                ),
                "weight": arc["weight"],
            }
        )
    return sorted(
        result,
        key=lambda item: (
            item["statementRole"],
            item["direction"],
            item["otherConcept"],
            item["weight"],
        ),
    )


def evaluate_interest_calculation_evidence(
    parsed_by_accession: dict[str, dict[str, Any]],
    *,
    statement_roles_by_accession: dict[str, dict[str, list[str]]],
    comparable_contexts_proven: bool,
    complete_accession_set: bool,
) -> dict[str, Any]:
    """
    Classify calculation evidence conservatively.

    Calculation networks can contradict an equivalence claim or support structural
    continuity. They cannot, by themselves, prove complete gross-interest scope.
    """
    if not parsed_by_accession:
        return {
            "policyVersion": SEC_INTEREST_CALCULATION_POLICY_VERSION,
            "status": "PARTIAL",
            "reasonCodes": ["CALCULATION_LINKBASE_MISSING_OR_NOT_COLLECTED"],
            "automaticScopeAuthorization": False,
        }

    contradictory = []
    neighborhoods: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(dict)
    for accession, parsed in sorted(parsed_by_accession.items()):
        for concept in (STRICT_INTEREST_CONCEPT, CONDITIONAL_INTEREST_CONCEPT):
            neighborhoods[accession][concept] = calculation_neighborhood(
                parsed,
                concept,
            )
        for item in neighborhoods[accession][CONDITIONAL_INTEREST_CONCEPT]:
            lowered = item["otherConcept"].replace(":", "").lower()
            if item["weight"] == "-1" or any(
                token in lowered for token in CONTRADICTORY_SCOPE_TOKENS
            ):
                contradictory.append(
                    {
                        "accession": accession,
                        **item,
                    }
                )
        strict_parents = {
            item["otherConcept"]
            for item in neighborhoods[accession][CONDITIONAL_INTEREST_CONCEPT]
            if item["direction"] == "COMPONENT_TO_TOTAL"
            and item["otherConcept"] == STRICT_INTEREST_CONCEPT
        }
        if strict_parents:
            siblings = {
                arc["childConcept"]
                for arc in _active_arcs(parsed)
                if arc["parentConcept"] == STRICT_INTEREST_CONCEPT
                and arc["childConcept"] != CONDITIONAL_INTEREST_CONCEPT
            }
            if siblings:
                contradictory.append(
                    {
                        "accession": accession,
                        "reason": "NONOPERATING_IS_SUBSET_OF_BROADER_INTEREST_TOTAL",
                        "siblingConcepts": sorted(siblings),
                    }
                )
    if contradictory:
        return {
            "policyVersion": SEC_INTEREST_CALCULATION_POLICY_VERSION,
            "status": "REJECT",
            "reasonCodes": ["POSITIVE_CALCULATION_SCOPE_CONTRADICTION"],
            "contradictions": contradictory,
            "automaticScopeAuthorization": False,
        }

    roles_consistent = True
    for concepts in statement_roles_by_accession.values():
        strict_roles = set(concepts.get(STRICT_INTEREST_CONCEPT, ()))
        conditional_roles = set(
            concepts.get(CONDITIONAL_INTEREST_CONCEPT, ())
        )
        if strict_roles and conditional_roles and not strict_roles & conditional_roles:
            roles_consistent = False

    structural_support = (
        complete_accession_set
        and comparable_contexts_proven
        and roles_consistent
        and any(
            concepts[STRICT_INTEREST_CONCEPT]
            for concepts in neighborhoods.values()
        )
        and any(
            concepts[CONDITIONAL_INTEREST_CONCEPT]
            for concepts in neighborhoods.values()
        )
    )
    reason_codes = [
        (
            "STRUCTURAL_CONTINUITY_SUPPORTED_BUT_ECONOMIC_SCOPE_NOT_PROVEN"
            if structural_support
            else "CALCULATION_STRUCTURE_INSUFFICIENT_FOR_CONTINUITY"
        )
    ]
    if any(not item["dtsCompletenessProven"] for item in parsed_by_accession.values()):
        reason_codes.append("DTS_COMPLETENESS_NOT_PROVEN")
    return {
        "policyVersion": SEC_INTEREST_CALCULATION_POLICY_VERSION,
        "status": "PARTIAL",
        "reasonCodes": sorted(reason_codes),
        "automaticScopeAuthorization": False,
    }
