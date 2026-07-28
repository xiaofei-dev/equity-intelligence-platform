import json
from datetime import UTC, datetime
from io import BytesIO

import pytest

from equity_analysis.provider_validation.sec_authoritative_overrides import (
    SecAuthoritativeTickerOverride,
    load_authoritative_ticker_overrides,
)
from equity_analysis.provider_validation.sec_edgar import SecEdgarClient, SecEdgarError


class Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def opener_for(payloads):
    def open_request(request, timeout):
        del timeout
        url = request.full_url
        payload = next(payload for pattern, payload in payloads.items() if pattern in url)
        return Response(json.dumps(payload).encode())

    return open_request


def test_sec_edgar_links_acceptance_timestamp_accession_and_xbrl_coverage() -> None:
    submissions = {
        "name": "Example Corporation",
        "filings": {
            "recent": {
                "form": ["8-K", "10-Q"],
                "filingDate": ["2026-07-01", "2026-05-01"],
                "acceptanceDateTime": [
                    "2026-07-01T12:00:00.000Z",
                    "2026-05-01T10:01:00.000Z",
                ],
                "accessionNumber": ["0000000001-26-000002", "0000000001-26-000001"],
                "reportDate": ["2026-07-01", "2026-03-31"],
            }
        },
    }
    required_tags = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {},
        "OperatingIncomeLoss": {},
        "NetIncomeLoss": {},
        "WeightedAverageNumberOfDilutedSharesOutstanding": {},
        "InterestExpenseNonOperating": {},
        "CashAndCashEquivalentsAtCarryingValue": {},
        "Assets": {},
        "StockholdersEquity": {},
        "NetCashProvidedByUsedInOperatingActivities": {},
        "PaymentsToAcquirePropertyPlantAndEquipment": {
            "units": {
                "USD": [
                    {
                        "accn": "0000000001-26-000001",
                        "form": "10-Q",
                        "filed": "2026-05-01",
                    }
                ]
            }
        },
    }
    company_facts = {
        "entityName": "Example Corporation",
        "facts": {"us-gaap": required_tags},
    }
    client = SecEdgarClient(
        user_agent="test@example.com",
        opener=opener_for(
            {
                "/submissions/": submissions,
                "/companyfacts/": company_facts,
            }
        ),
        sleeper=lambda _seconds: None,
    )

    filing = client.fetch_latest_filing("1", "TEST")
    facts = client.fetch_facts_summary("1", filing.accession_number)

    assert filing.form == "10-Q"
    assert filing.accession_number == "0000000001-26-000001"
    assert filing.acceptance_datetime.isoformat() == "2026-05-01T10:01:00+00:00"
    assert all(facts.required_tag_groups_present.values())
    assert facts.matching_accession_fact_count == 1


def test_sec_edgar_lookup_preserves_leading_zero_cik() -> None:
    client = SecEdgarClient(
        user_agent="test@example.com",
        opener=opener_for(
            {
                "company_tickers.json": {
                    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}
                }
            }
        ),
        sleeper=lambda _seconds: None,
    )

    cik, name = client.lookup_cik("aapl")

    assert cik == "0000320193"
    assert name == "Apple Inc."


def test_sec_edgar_uses_authoritative_override_when_official_snapshot_omits_ticker() -> None:
    override = SecAuthoritativeTickerOverride(
        ticker="LANC",
        issuer_legal_name="Lancaster Colony Corporation",
        cik="0000057515",
        source_reference="https://www.sec.gov/Archives/edgar/data/57515/example.htm",
        evidence_hash="A" * 64,
        observed_at=datetime(2026, 7, 27, tzinfo=UTC),
        effective_at=datetime(2025, 2, 18, tzinfo=UTC),
        expires_at=None,
    )
    client = SecEdgarClient(
        user_agent="test@example.com",
        opener=opener_for({"company_tickers.json": {}}),
        sleeper=lambda _seconds: None,
        authoritative_ticker_overrides={"LANC": override},
    )

    assert client.lookup_cik(" lanc ") == (
        "0000057515",
        "Lancaster Colony Corporation",
    )


def test_sec_edgar_prefers_matching_official_mapping_over_override() -> None:
    override = SecAuthoritativeTickerOverride(
        ticker="LANC",
        issuer_legal_name="Lancaster Colony Corporation",
        cik="0000057515",
        source_reference="https://www.sec.gov/example",
        evidence_hash="A" * 64,
        observed_at=datetime(2026, 7, 27, tzinfo=UTC),
        effective_at=datetime(2025, 2, 18, tzinfo=UTC),
        expires_at=None,
    )
    client = SecEdgarClient(
        user_agent="test@example.com",
        opener=opener_for(
            {
                "company_tickers.json": {
                    "0": {
                        "cik_str": 57515,
                        "ticker": "LANC",
                        "title": "LANCASTER COLONY CORP",
                    }
                }
            }
        ),
        sleeper=lambda _seconds: None,
        authoritative_ticker_overrides={"LANC": override},
    )

    assert client.lookup_cik("LANC") == ("0000057515", "LANCASTER COLONY CORP")


def test_sec_edgar_rejects_official_mapping_override_conflict() -> None:
    override = SecAuthoritativeTickerOverride(
        ticker="LANC",
        issuer_legal_name="Lancaster Colony Corporation",
        cik="0000057515",
        source_reference="https://www.sec.gov/example",
        evidence_hash="A" * 64,
        observed_at=datetime(2026, 7, 27, tzinfo=UTC),
        effective_at=datetime(2025, 2, 18, tzinfo=UTC),
        expires_at=None,
    )
    client = SecEdgarClient(
        user_agent="test@example.com",
        opener=opener_for(
            {
                "company_tickers.json": {
                    "0": {
                        "cik_str": 1,
                        "ticker": "LANC",
                        "title": "Wrong Issuer",
                    }
                }
            }
        ),
        sleeper=lambda _seconds: None,
        authoritative_ticker_overrides={"LANC": override},
    )

    with pytest.raises(SecEdgarError) as captured:
        client.lookup_cik("LANC")

    assert captured.value.code == "SEC_TICKER_CIK_CONFLICT"


def test_authoritative_registry_preserves_lineage_and_normalizes_ticker() -> None:
    override = load_authoritative_ticker_overrides(
        as_of=datetime(2026, 7, 27, 19, tzinfo=UTC)
    )["LANC"]

    assert override.cik == "0000057515"
    assert override.ticker == "LANC"
    assert override.source_reference.startswith("https://www.sec.gov/")
    assert override.evidence_hash == (
        "7C23CDE98DAFFFE79A248754B15D33EFFD33CA9410B77030261DBA4BF13B84BD"
    )


def test_sec_edgar_rejects_missing_supported_filing() -> None:
    client = SecEdgarClient(
        user_agent="test@example.com",
        opener=opener_for(
            {
                "/submissions/": {
                    "name": "Example Fund",
                    "filings": {"recent": {"form": ["N-CSR"]}},
                }
            }
        ),
        sleeper=lambda _seconds: None,
    )

    with pytest.raises(SecEdgarError, match="no supported filing"):
        client.fetch_latest_filing("1", "FUND")


def test_sec_edgar_accepts_alternative_property_plant_and_equipment_tag() -> None:
    client = SecEdgarClient(
        user_agent="test@example.com",
        opener=opener_for(
            {
                "/companyfacts/": {
                    "entityName": "Example Corporation",
                    "facts": {
                        "us-gaap": {
                            "PaymentsToAcquireOtherPropertyPlantAndEquipment": {
                                "units": {"USD": []}
                            }
                        }
                    },
                }
            }
        ),
        sleeper=lambda _seconds: None,
    )

    facts = client.fetch_facts_summary("1", "0000000001-26-000001")

    assert facts.required_tag_groups_present["capital_expenditure"] is True


def test_sec_edgar_selects_only_filings_available_by_pit_cutoff() -> None:
    submissions = {
        "name": "Example Corporation",
        "filings": {
            "recent": {
                "form": ["10-Q/A", "10-Q", "10-K"],
                "filingDate": ["2026-05-10", "2026-05-01", "2026-02-01"],
                "acceptanceDateTime": [
                    "2026-05-10T12:00:00.000Z",
                    "2026-05-01T10:01:00.000Z",
                    "2026-02-01T09:00:00.000Z",
                ],
                "accessionNumber": [
                    "0000000001-26-000003",
                    "0000000001-26-000002",
                    "0000000001-26-000001",
                ],
                "reportDate": ["2026-03-31", "2026-03-31", "2025-12-31"],
            }
        },
    }
    client = SecEdgarClient(
        user_agent="test@example.com",
        opener=opener_for({"/submissions/": submissions}),
        sleeper=lambda _seconds: None,
    )

    before_quarterly = client.fetch_filing_as_of(
        "1",
        "TEST",
        datetime(2026, 4, 30, 23, 59, tzinfo=UTC),
    )
    after_quarterly = client.fetch_filing_as_of(
        "1",
        "TEST",
        datetime(2026, 5, 2, tzinfo=UTC),
    )
    after_amendment = client.fetch_filing_as_of(
        "1",
        "TEST",
        datetime(2026, 5, 11, tzinfo=UTC),
    )

    assert before_quarterly.accession_number == "0000000001-26-000001"
    assert after_quarterly.accession_number == "0000000001-26-000002"
    assert after_amendment.accession_number == "0000000001-26-000003"


def test_sec_edgar_rejects_timezone_naive_pit_cutoff() -> None:
    client = SecEdgarClient(
        user_agent="test@example.com",
        opener=opener_for({}),
        sleeper=lambda _seconds: None,
    )

    with pytest.raises(ValueError, match="timezone"):
        client.fetch_filing_as_of("1", "TEST", datetime(2026, 5, 1))


def test_sec_edgar_loads_historical_submission_file_for_older_cutoff() -> None:
    current = {
        "name": "Example Corporation",
        "filings": {
            "recent": {
                "form": ["10-Q"],
                "filingDate": ["2026-05-01"],
                "acceptanceDateTime": ["2026-05-01T10:01:00.000Z"],
                "accessionNumber": ["0000000001-26-000001"],
                "reportDate": ["2026-03-31"],
            },
            "files": [
                {
                    "name": "CIK0000000001-submissions-001.json",
                    "filingFrom": "2020-01-01",
                    "filingTo": "2024-12-31",
                }
            ],
        },
    }
    historical = {
        "form": ["10-Q"],
        "filingDate": ["2022-05-01"],
        "acceptanceDateTime": ["2022-05-01T10:01:00.000Z"],
        "accessionNumber": ["0000000001-22-000001"],
        "reportDate": ["2022-03-31"],
    }
    client = SecEdgarClient(
        user_agent="test@example.com",
        opener=opener_for(
            {
                "CIK0000000001.json": current,
                "CIK0000000001-submissions-001.json": historical,
            }
        ),
        sleeper=lambda _seconds: None,
    )

    filing = client.fetch_filing_as_of(
        "1",
        "TEST",
        datetime(2022, 6, 1, tzinfo=UTC),
    )

    assert filing.accession_number == "0000000001-22-000001"
