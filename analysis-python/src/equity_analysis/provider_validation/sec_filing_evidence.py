from __future__ import annotations

import html
import re
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from equity_analysis.provider_validation.expansion_gate import canonical_hash

SEC_FILING_EVIDENCE_SCHEMA_VERSION = "sec-filing-evidence-v1.1.0"
SEC_INLINE_XBRL_PARSER_VERSION = "sec-inline-xbrl-parser-v1.1.0"
SEC_PRESENTATION_PARSER_VERSION = "sec-presentation-context-parser-v1.0.0"
SEC_ECONOMIC_SCOPE_POLICY_VERSION = "sec-economic-scope-policy-v1.1.0"
SEC_DEBT_COMPLETENESS_POLICY_VERSION = "sec-debt-completeness-policy-v1.0.0"
SEC_TRADED_CLASS_POLICY_VERSION = "sec-traded-class-identity-policy-v1.0.0"

PREFERRED_INTEREST_CONCEPT = "us-gaap:InterestExpense"
CONDITIONAL_NONOPERATING_INTEREST_CONCEPT = (
    "us-gaap:InterestExpenseNonoperating"
)
DEBT_ONLY_INTEREST_CONCEPTS = frozenset(
    {
        "us-gaap:InterestAndDebtExpense",
        "us-gaap:InterestExpenseDebt",
    }
)
MIXED_INTEREST_CONCEPTS = frozenset(
    {
        "us-gaap:InterestIncomeExpenseNonoperatingNet",
        "us-gaap:InterestIncomeExpenseNonOperatingNet",
    }
)
DEBT_CONCEPTS = frozenset(
    {
        "us-gaap:LongTermDebtCurrent",
        "us-gaap:LongTermDebtNoncurrent",
        "us-gaap:ShortTermBorrowings",
        "us-gaap:DebtCurrent",
        "us-gaap:LongTermDebt",
        "us-gaap:LongTermDebtAndFinanceLeaseObligationsCurrent",
        "us-gaap:LongTermDebtAndFinanceLeaseObligationsNoncurrent",
    }
)
SHARE_CONCEPT = "dei:EntityCommonStockSharesOutstanding"
TRADING_SYMBOL_CONCEPT = "dei:TradingSymbol"
SECURITY_TITLE_CONCEPT = "dei:Security12bTitle"


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest().upper()


def bytes_sha256(value: bytes) -> str:
    return sha256(value).hexdigest().upper()


def accession_without_dashes(accession: str) -> str:
    normalized = accession.replace("-", "")
    if not re.fullmatch(r"\d{18}", normalized):
        raise ValueError("SEC_ACCESSION_INVALID")
    return normalized


def filing_archive_root(cik: str, accession: str) -> str:
    normalized_cik = str(int(cik))
    return (
        f"https://www.sec.gov/Archives/edgar/data/{normalized_cik}/"
        f"{accession_without_dashes(accession)}/"
    )


def select_latest_annual_filing(submissions: dict[str, Any]) -> dict[str, str]:
    recent = submissions.get("filings", {}).get("recent", {})
    rows = zip(
        recent.get("accessionNumber", ()),
        recent.get("form", ()),
        recent.get("filingDate", ()),
        recent.get("acceptanceDateTime", ()),
        recent.get("primaryDocument", ()),
        strict=False,
    )
    eligible = [
        {
            "accession": str(accession),
            "form": str(form),
            "filed": str(filed),
            "accepted": str(accepted),
            "primaryDocument": str(primary),
        }
        for accession, form, filed, accepted, primary in rows
        if str(form) in {"10-K", "10-K/A"} and accession and primary
    ]
    if not eligible:
        raise ValueError("SEC_NO_ANNUAL_FILING_IN_SUBMISSIONS")
    return max(
        eligible,
        key=lambda item: (
            item["filed"],
            item["accepted"],
            item["accession"],
        ),
    )


def select_filing_documents(
    index_payload: dict[str, Any],
    *,
    primary_document: str,
) -> dict[str, str]:
    items = index_payload.get("directory", {}).get("item", ())
    names = sorted(
        str(item.get("name"))
        for item in items
        if isinstance(item, dict) and item.get("name")
    )
    if primary_document not in names:
        raise ValueError("SEC_PRIMARY_DOCUMENT_NOT_IN_FILING_INDEX")

    def one(suffix: str) -> str:
        matches = [name for name in names if name.lower().endswith(suffix)]
        if len(matches) != 1:
            raise ValueError(f"SEC_FILING_LINKBASE_{suffix.upper()}_NOT_UNIQUE")
        return matches[0]

    return {
        "primary": primary_document,
        "presentation": one("_pre.xml"),
        "labels": one("_lab.xml"),
    }


@dataclass
class _ContextBuilder:
    identifier: str | None = None
    start: str | None = None
    end: str | None = None
    instant: str | None = None
    dimensions: list[dict[str, str]] | None = None


class _InlineXbrlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.contexts: dict[str, dict[str, Any]] = {}
        self.facts: list[dict[str, Any]] = []
        self._context_id: str | None = None
        self._context: _ContextBuilder | None = None
        self._capture: str | None = None
        self._fact: dict[str, Any] | None = None
        self._fact_text: list[str] = []

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {key.lower(): value or "" for key, value in attrs}

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = self._attrs(attrs)
        lowered = tag.lower()
        if lowered.endswith(":context"):
            self._context_id = attributes.get("id")
            self._context = _ContextBuilder(dimensions=[])
            return
        if self._context is not None:
            if lowered.endswith(":identifier"):
                self._capture = "identifier"
            elif lowered.endswith(":startdate"):
                self._capture = "start"
            elif lowered.endswith(":enddate"):
                self._capture = "end"
            elif lowered.endswith(":instant"):
                self._capture = "instant"
            elif lowered.endswith(":explicitmember"):
                self._context.dimensions.append(
                    {
                        "dimension": attributes.get("dimension", ""),
                        "member": "",
                    }
                )
                self._capture = "member"
        if lowered in {"ix:nonfraction", "ix:nonnumeric"}:
            self._fact = {
                "concept": attributes.get("name"),
                "contextRef": attributes.get("contextref"),
                "unitRef": attributes.get("unitref"),
                "decimals": attributes.get("decimals"),
                "scale": attributes.get("scale"),
                "sign": attributes.get("sign"),
                "format": attributes.get("format"),
                "nil": attributes.get("xsi:nil", "").lower() == "true",
                "inlineType": lowered,
            }
            self._fact_text = []

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if not stripped:
            return
        if self._fact is not None:
            self._fact_text.append(stripped)
        if self._context is None or self._capture is None:
            return
        if self._capture == "member" and self._context.dimensions:
            self._context.dimensions[-1]["member"] += stripped
        else:
            setattr(self._context, self._capture, stripped)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered.endswith(
            (":identifier", ":startdate", ":enddate", ":instant", ":explicitmember")
        ):
            self._capture = None
        if lowered.endswith(":context") and self._context_id and self._context:
            self.contexts[self._context_id] = {
                "entityIdentifier": self._context.identifier,
                "periodStart": self._context.start,
                "periodEnd": self._context.end,
                "instant": self._context.instant,
                "dimensions": sorted(
                    self._context.dimensions or [],
                    key=lambda item: (item["dimension"], item["member"]),
                ),
            }
            self._context_id = None
            self._context = None
            self._capture = None
        if lowered in {"ix:nonfraction", "ix:nonnumeric"} and self._fact is not None:
            self._fact["text"] = html.unescape(" ".join(self._fact_text)).strip()
            self.facts.append(self._fact)
            self._fact = None
            self._fact_text = []


def parse_inline_xbrl(document: bytes) -> dict[str, Any]:
    parser = _InlineXbrlParser()
    parser.feed(document.decode("utf-8", errors="replace"))
    facts = []
    for fact in parser.facts:
        context = parser.contexts.get(str(fact["contextRef"]))
        if context is None:
            continue
        facts.append({**fact, "context": context})
    return {
        "parserVersion": SEC_INLINE_XBRL_PARSER_VERSION,
        "contextCount": len(parser.contexts),
        "factCount": len(facts),
        "facts": facts,
    }


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def parse_presentation_linkbase(
    presentation: bytes,
    labels: bytes,
) -> dict[str, list[dict[str, str | None]]]:
    presentation_root = ElementTree.fromstring(presentation)
    label_root = ElementTree.fromstring(labels)
    label_text_by_id = {
        element.attrib.get("{http://www.w3.org/1999/xlink}label", ""): (
            "".join(element.itertext()).strip()
        )
        for element in label_root.iter()
        if _local_name(element.tag) == "label"
    }
    concept_by_locator = {}
    role_by_link: dict[int, str] = {}
    evidence: dict[str, list[dict[str, str | None]]] = defaultdict(list)
    for link in presentation_root.iter():
        if _local_name(link.tag) != "presentationLink":
            continue
        role = link.attrib.get("{http://www.w3.org/1999/xlink}role", "")
        role_by_link[id(link)] = role
        local_locators = {}
        for element in link:
            if _local_name(element.tag) != "loc":
                continue
            label = element.attrib.get("{http://www.w3.org/1999/xlink}label", "")
            href = element.attrib.get("{http://www.w3.org/1999/xlink}href", "")
            concept = href.rsplit("#", 1)[-1].replace("_", ":", 1)
            local_locators[label] = concept
            concept_by_locator[label] = concept
        for element in link:
            if _local_name(element.tag) != "presentationArc":
                continue
            child = element.attrib.get("{http://www.w3.org/1999/xlink}to", "")
            concept = local_locators.get(child)
            if not concept:
                continue
            preferred = element.attrib.get("preferredLabel") or element.attrib.get(
                "{http://www.xbrl.org/2003/linkbase}preferredLabel"
            )
            evidence[concept].append(
                {
                    "statementRole": role,
                    "preferredLabelRole": preferred,
                    "presentationOrder": element.attrib.get("order"),
                    "presentationLabel": label_text_by_id.get(child),
                }
            )
    return {
        concept: sorted(
            rows,
            key=lambda row: (
                row["statementRole"] or "",
                row["presentationOrder"] or "",
            ),
        )
        for concept, rows in sorted(evidence.items())
    }


def classify_interest_scope(
    concept: str,
    presentation_rows: list[dict[str, str | None]],
) -> dict[str, Any]:
    labels = " ".join(
        str(row.get("presentationLabel") or "") for row in presentation_rows
    ).lower()
    if concept == PREFERRED_INTEREST_CONCEPT:
        status = "PREFERRED_TOTAL_GROSS_INTEREST_CANDIDATE"
    elif concept == CONDITIONAL_NONOPERATING_INTEREST_CONCEPT:
        status = "CONDITIONAL_NONOPERATING_INTEREST"
    elif concept in DEBT_ONLY_INTEREST_CONCEPTS:
        status = "DEBT_ONLY_NOT_EQUIVALENT"
    elif concept in MIXED_INTEREST_CONCEPTS:
        status = "MIXED_OR_NET_NOT_EQUIVALENT"
    else:
        status = "UNMAPPED_INTEREST_SCOPE"
    if any(token in labels for token in ("net interest", "capitalized interest")):
        status = "MIXED_OR_NET_NOT_EQUIVALENT"
    return {
        "policyVersion": SEC_ECONOMIC_SCOPE_POLICY_VERSION,
        "concept": concept,
        "status": status,
        "acceptedAsStrictInterestExpense": False,
        "issuerConsistencyEvidenceRequired": status
        in {
            "PREFERRED_TOTAL_GROSS_INTEREST_CANDIDATE",
            "CONDITIONAL_NONOPERATING_INTEREST",
        },
    }


def evaluate_debt_completeness(
    concepts: set[str],
    presentation: dict[str, list[dict[str, str | None]]],
) -> dict[str, Any]:
    observed = sorted(concepts & DEBT_CONCEPTS)
    roles = sorted(
        {
            str(row["statementRole"])
            for concept in observed
            for row in presentation.get(concept, ())
            if row.get("statementRole")
        }
    )
    return {
        "policyVersion": SEC_DEBT_COMPLETENESS_POLICY_VERSION,
        "observedDebtConcepts": observed,
        "statementRoles": roles,
        "status": "NOT_PROVEN",
        "reasonCode": "DEBT_NON_OVERLAP_AND_COMPLETENESS_REQUIRE_ISSUER_RULE",
        "totalDebtAuthorized": False,
    }


def evaluate_traded_class_identity(
    facts: list[dict[str, Any]],
    *,
    requested_symbol: str,
) -> dict[str, Any]:
    symbols = sorted(
        {
            str(fact["text"]).upper()
            for fact in facts
            if fact.get("concept") == TRADING_SYMBOL_CONCEPT and fact.get("text")
        }
    )
    titles = sorted(
        {
            str(fact["text"])
            for fact in facts
            if fact.get("concept") == SECURITY_TITLE_CONCEPT and fact.get("text")
        }
    )
    share_contexts = [
        fact["context"]
        for fact in facts
        if fact.get("concept") == SHARE_CONCEPT
    ]
    class_members = sorted(
        {
            dimension["member"]
            for context in share_contexts
            for dimension in context.get("dimensions", ())
            if dimension.get("member")
        }
    )
    symbol_matches = symbols == [requested_symbol.upper()]
    class_evidence = bool(titles) and bool(class_members)
    proven = symbol_matches and class_evidence
    return {
        "policyVersion": SEC_TRADED_CLASS_POLICY_VERSION,
        "requestedSymbol": requested_symbol.upper(),
        "filingTradingSymbols": symbols,
        "securityTitles": titles,
        "shareClassMembers": class_members,
        "status": "PROVEN" if proven else "NOT_PROVEN",
        "reasonCode": (
            None
            if proven
            else "SEC_INSTANT_SHARES_NOT_DURABLY_LINKED_TO_TRADED_CLASS"
        ),
        "historicalMarketCapSharesAuthorized": proven,
    }


def build_filing_evidence(
    *,
    symbol: str,
    cik: str,
    filing: dict[str, str],
    source_references: dict[str, str],
    source_hashes: dict[str, str],
    inline_document: bytes,
    presentation_document: bytes,
    label_document: bytes,
    ingested_at: str,
) -> dict[str, Any]:
    inline = parse_inline_xbrl(inline_document)
    presentation = parse_presentation_linkbase(
        presentation_document,
        label_document,
    )
    relevant_facts = [
        fact
        for fact in inline["facts"]
        if fact.get("concept")
        in (
            {
                PREFERRED_INTEREST_CONCEPT,
                CONDITIONAL_NONOPERATING_INTEREST_CONCEPT,
                *DEBT_ONLY_INTEREST_CONCEPTS,
                *MIXED_INTEREST_CONCEPTS,
                *DEBT_CONCEPTS,
                SHARE_CONCEPT,
                TRADING_SYMBOL_CONCEPT,
                SECURITY_TITLE_CONCEPT,
            }
        )
    ]
    interest_evidence = [
        {
            "concept": fact["concept"],
            "contextRef": fact["contextRef"],
            "context": fact["context"],
            "unitRef": fact.get("unitRef"),
            "nil": fact["nil"],
            "presentation": presentation.get(fact["concept"], []),
            "scope": classify_interest_scope(
                fact["concept"],
                presentation.get(fact["concept"], []),
            ),
            "calculationEvidenceStatus": (
                "NOT_COLLECTED_NOT_IN_APPROVED_ENDPOINT_SET"
            ),
        }
        for fact in relevant_facts
        if "Interest" in str(fact.get("concept"))
    ]
    payload = {
        "schemaVersion": SEC_FILING_EVIDENCE_SCHEMA_VERSION,
        "parserVersions": {
            "inlineXbrl": SEC_INLINE_XBRL_PARSER_VERSION,
            "presentation": SEC_PRESENTATION_PARSER_VERSION,
        },
        "symbol": symbol,
        "entityId": f"CIK:{cik}",
        "accession": filing["accession"],
        "form": filing["form"],
        "filedAt": filing["filed"],
        "acceptedAt": filing["accepted"],
        "availableAt": filing["accepted"],
        "ingestedAt": ingested_at,
        "sourceReferences": source_references,
        "sourceHashes": source_hashes,
        "inlineContextCount": inline["contextCount"],
        "inlineFactCount": inline["factCount"],
        "interestEvidence": interest_evidence,
        "debtEvidence": evaluate_debt_completeness(
            {str(fact["concept"]) for fact in relevant_facts},
            presentation,
        ),
        "tradedClassEvidence": evaluate_traded_class_identity(
            relevant_facts,
            requested_symbol=symbol,
        ),
        "rawFilingValuesIncluded": False,
    }
    payload["contentHash"] = canonical_hash(payload)
    return payload
