from equity_analysis.provider_validation.sec_filing_evidence import (
    SEC_FILING_EVIDENCE_SCHEMA_VERSION,
    build_filing_evidence,
    classify_interest_scope,
    evaluate_debt_completeness,
    evaluate_traded_class_identity,
    parse_inline_xbrl,
    parse_presentation_linkbase,
    select_filing_documents,
    select_latest_annual_filing,
)

INLINE = b"""
<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
 xmlns:xbrli="http://www.xbrl.org/2003/instance">
<xbrli:context id="D1"><xbrli:entity><xbrli:identifier>0001</xbrli:identifier>
</xbrli:entity><xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate>
<xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
<ix:nonFraction name="us-gaap:InterestExpenseNonoperating" contextRef="D1"
 unitRef="USD">123456789</ix:nonFraction>
<ix:nonFraction name="us-gaap:InterestExpense" contextRef="D1"
 unitRef="USD">123456789</ix:nonFraction>
<ix:nonNumeric name="dei:TradingSymbol" contextRef="D1">TEST</ix:nonNumeric>
<ix:nonNumeric name="dei:Security12bTitle" contextRef="D1">Class A Common</ix:nonNumeric>
</html>
"""

PRESENTATION = b"""<?xml version="1.0"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
 xmlns:xlink="http://www.w3.org/1999/xlink">
 <link:presentationLink xlink:role="http://example/role/IncomeStatement">
  <link:loc xlink:label="interest" xlink:href="test.xsd#us-gaap_InterestExpenseNonoperating"/>
  <link:presentationArc xlink:to="interest" order="1"/>
 </link:presentationLink>
</link:linkbase>"""

LABELS = b"""<?xml version="1.0"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
 xmlns:xlink="http://www.w3.org/1999/xlink">
 <link:label xlink:label="interest">Interest expense, non-operating</link:label>
</link:linkbase>"""


def test_filing_selection_and_document_discovery_are_deterministic() -> None:
    submissions = {
        "filings": {
            "recent": {
                "accessionNumber": ["1", "2"],
                "form": ["10-K", "10-Q"],
                "filingDate": ["2026-01-01", "2026-04-01"],
                "acceptanceDateTime": ["20260101120000", "20260401120000"],
                "primaryDocument": ["annual.htm", "quarter.htm"],
            }
        }
    }
    assert select_latest_annual_filing(submissions)["primaryDocument"] == "annual.htm"
    documents = select_filing_documents(
        {
            "directory": {
                "item": [
                    {"name": "annual.htm"},
                    {"name": "issuer_pre.xml"},
                    {"name": "issuer_lab.xml"},
                ]
            }
        },
        primary_document="annual.htm",
    )
    assert documents == {
        "primary": "annual.htm",
        "presentation": "issuer_pre.xml",
        "labels": "issuer_lab.xml",
    }


def test_inline_parser_preserves_context_without_exposing_value_in_evidence() -> None:
    parsed = parse_inline_xbrl(INLINE)
    assert parsed["contextCount"] == 1
    assert parsed["facts"][0]["context"]["periodStart"] == "2025-01-01"

    presentation = parse_presentation_linkbase(PRESENTATION, LABELS)
    assert "us-gaap:InterestExpenseNonoperating" in presentation
    scope = classify_interest_scope(
        "us-gaap:InterestExpenseNonoperating",
        presentation["us-gaap:InterestExpenseNonoperating"],
    )
    assert scope["status"] == "CONDITIONAL_NONOPERATING_INTEREST"
    assert not scope["acceptedAsStrictInterestExpense"]

    evidence = build_filing_evidence(
        symbol="TEST",
        cik="0000000001",
        filing={
            "accession": "0000000001-26-000001",
            "form": "10-K",
            "filed": "2026-01-01",
            "accepted": "2026-01-01T12:00:00Z",
        },
        source_references={
            "filing": "sec-edgar:filing:0000000001-26-000001",
            "presentation": "sec-edgar:presentation:0000000001-26-000001",
            "labels": "sec-edgar:labels:0000000001-26-000001",
        },
        source_hashes={"filing": "A" * 64, "presentation": "B" * 64, "labels": "C" * 64},
        inline_document=INLINE,
        presentation_document=PRESENTATION,
        label_document=LABELS,
        ingested_at="2026-07-27T00:00:00Z",
    )
    assert evidence["schemaVersion"] == SEC_FILING_EVIDENCE_SCHEMA_VERSION
    assert (
        evidence["interestEvidence"][0]["scope"]["status"]
        == "CONDITIONAL_NONOPERATING_INTEREST"
    )
    assert (
        evidence["interestEvidence"][0]["calculationEvidenceStatus"]
        == "NOT_COLLECTED_NOT_IN_APPROVED_ENDPOINT_SET"
    )
    assert {
        item["concept"] for item in evidence["interestEvidence"]
    } == {
        "us-gaap:InterestExpense",
        "us-gaap:InterestExpenseNonoperating",
    }
    assert "123456789" not in str(evidence)
    assert evidence["rawFilingValuesIncluded"] is False


def test_broad_interest_debt_and_share_class_remain_unproven() -> None:
    assert classify_interest_scope("us-gaap:InterestExpense", [])["status"] == (
        "PREFERRED_TOTAL_GROSS_INTEREST_CANDIDATE"
    )
    debt = evaluate_debt_completeness(
        {"us-gaap:LongTermDebtCurrent", "us-gaap:LongTermDebtNoncurrent"},
        {},
    )
    assert debt["status"] == "NOT_PROVEN"
    assert not debt["totalDebtAuthorized"]

    parsed = parse_inline_xbrl(INLINE)
    shares = evaluate_traded_class_identity(parsed["facts"], requested_symbol="TEST")
    assert shares["status"] == "NOT_PROVEN"
    assert not shares["historicalMarketCapSharesAuthorized"]
