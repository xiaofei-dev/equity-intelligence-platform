import json
from io import BytesIO

import pytest

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
