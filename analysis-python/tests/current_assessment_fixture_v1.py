"""Synthetic Git-safe fixtures for current Fundamental Value tests."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from equity_analysis.fundamental_value.current_assessment_execution_v1 import (
    CurrentPriceRequestV1,
    decode_current_eodhd_price_response_v1,
)
from equity_analysis.fundamental_value.current_assessment_v1 import (
    source_seal_from_bytes_v1,
)
from equity_analysis.fundamental_value.identity_projection_v2 import (
    ProjectedIdentityMemberV2,
)
from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    TransportResponse,
)

PERIODS = (
    "2024-09-30",
    "2024-12-31",
    "2025-03-31",
    "2025-06-30",
    "2025-09-30",
    "2025-12-31",
    "2026-03-31",
    "2026-06-30",
)

_SYNTHETIC_AUTHORITY_ID = "25000000-0000-4000-8000-000000000001"
_SYNTHETIC_GOOG = tuple(
    f"25000000-0000-4000-8000-00000000010{ordinal}" for ordinal in range(1, 7)
)
_SYNTHETIC_FOX = tuple(
    f"25000000-0000-4000-8000-00000000020{ordinal}" for ordinal in range(1, 7)
)
_SYNTHETIC_MSFT = tuple(
    f"25000000-0000-4000-8000-00000000030{ordinal}" for ordinal in range(1, 7)
)


def _quarter(period: str, ordinal: int) -> dict[str, object]:
    return {
        "date": period,
        "filing_date": "2026-07-20" if ordinal == 7 else period,
        "currency_symbol": "USD",
        "totalRevenue": str(100 + ordinal * 3),
        "operatingIncome": str(20 + ordinal),
        "netIncome": str(15 + ordinal),
        "incomeBeforeTax": str(18 + ordinal),
        "incomeTaxExpense": str(3.6 + ordinal / 10),
        "interestExpense": "1",
        "depreciationAndAmortization": "5",
        "ebitda": str(25 + ordinal),
        "totalCashFromOperatingActivities": str(22 + ordinal),
        "capitalExpenditures": "-6",
        "changeInWorkingCapital": "-2",
        "freeCashFlow": str(16 + ordinal),
        "dividendsPaid": "-2",
        "salePurchaseOfStock": "-1",
    }


def _balance(period: str, ordinal: int) -> dict[str, object]:
    return {
        "date": period,
        "filing_date": "2026-07-20" if ordinal == 7 else period,
        "currency_symbol": "USD",
        "cashAndShortTermInvestments": str(45 + ordinal * 2),
        "shortLongTermDebtTotal": "40",
        "totalCurrentAssets": str(70 + ordinal),
        "totalCurrentLiabilities": "40",
        "totalStockholderEquity": str(180 + ordinal * 3),
        "goodWill": "10",
        "totalAssets": str(280 + ordinal * 4),
        "commonStockSharesOutstanding": str(11 - ordinal / 10),
    }


def fundamentals_fixture_v1() -> dict[str, object]:
    income_quarters = {
        f"q{index}": _quarter(period, index)
        for index, period in enumerate(PERIODS)
    }
    cash_quarters = copy.deepcopy(income_quarters)
    balance_quarters = {
        f"q{index}": _balance(period, index)
        for index, period in enumerate(PERIODS)
    }
    years = (
        "2022-06-30",
        "2023-06-30",
        "2024-06-30",
        "2025-06-30",
        "2026-06-30",
    )
    income_yearly = {
        f"y{index}": {
            "date": period,
            "filing_date": "2026-07-20" if index == 4 else period,
            "currency_symbol": "USD",
            "totalRevenue": str(300 + index * 50),
        }
        for index, period in enumerate(years)
    }
    cash_yearly = {
        f"y{index}": {
            "date": period,
            "filing_date": "2026-07-20" if index == 4 else period,
            "currency_symbol": "USD",
            "freeCashFlow": str(30 + index * 5),
        }
        for index, period in enumerate(years)
    }
    return {
        "General": {
            "Code": "ACME",
            "CurrencyCode": "USD",
            "Type": "Common Stock",
            "Sector": "Technology",
            "Industry": "Software - Infrastructure",
            "UpdatedAt": "2026-07-20",
        },
        "Technicals": {"Beta": "1.0"},
        "Valuation": {"EnterpriseValueEbitda": "10"},
        "Financials": {
            "Income_Statement": {
                "quarterly": income_quarters,
                "yearly": income_yearly,
            },
            "Cash_Flow": {
                "quarterly": cash_quarters,
                "yearly": cash_yearly,
            },
            "Balance_Sheet": {"quarterly": balance_quarters},
        },
    }


def price_fixture_v1(*, trading_date: str = "2026-07-31") -> dict[str, object]:
    return {
        "schemaVersion": "YAHOO-DAILY-PRICE-v1.0.0",
        "providerCode": "yfinance",
        "symbol": "ACME",
        "bars": [
            {
                "tradingDate": trading_date,
                "raw": {
                    "open": "19",
                    "high": "21",
                    "low": "18",
                    "close": "20",
                    "adjustedClose": "20",
                },
                "volume": 1_000_000,
                "tactical": {"sessionComplete": True},
            }
        ],
    }


def eodhd_price_fixture_v1(
    identity: ProjectedIdentityMemberV2,
    *,
    trading_date: str,
    available_at: datetime,
) -> dict[str, object]:
    """Build the exact canonical output of the frozen EODHD price decoder."""

    base = price_fixture_v1(trading_date=trading_date)
    raw_rows = []
    for bar in base["bars"]:
        raw_price = bar["raw"]
        raw_rows.append(
            {
                "date": bar["tradingDate"],
                "open": raw_price["open"],
                "high": raw_price["high"],
                "low": raw_price["low"],
                "close": raw_price["close"],
                "adjusted_close": raw_price["adjustedClose"],
                "volume": bar["volume"],
            }
        )
    end_date = date.fromisoformat(trading_date)
    start_date = end_date - timedelta(days=14)
    request = CurrentPriceRequestV1(
        ordinal=identity.ordinal,
        symbol=identity.ticker,
        security_id=identity.security_id,
        company_id=identity.company_id,
        instrument_id=identity.instrument_id,
        share_class_id=identity.share_class_id,
        listing_id=identity.listing_id,
        ticker_assignment_id=identity.ticker_assignment_id,
        mic=identity.mic,
        currency=identity.currency,
        endpoint_path=(
            f"/api/eod/{identity.ticker}.US?fmt=json&from={start_date.isoformat()}"
            f"&to={end_date.isoformat()}&period=d"
        ),
        request_identity="A" * 64,
    )
    payload, _ = decode_current_eodhd_price_response_v1(
        request,
        TransportResponse(
            status_code=200,
            headers=(("date", format_datetime(available_at, usegmt=True)),),
            body=json.dumps(raw_rows, sort_keys=True).encode("utf-8"),
        ),
    )
    return payload


def source_fixture_v1(
    payload: dict[str, object],
    provider: str,
    available_at: datetime,
    *,
    request_identity: str = "A" * 64,
    plan_hash: str = "B" * 64,
    checkpoint_reference: str | None = None,
):
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    return source_seal_from_bytes_v1(
        provider_code=provider,
        schema_version=f"{provider}-schema-v1",
        source_reference=f"private://{provider.lower()}/acme",
        raw=raw,
        canonical_payload=payload,
        available_at=available_at,
        retrieved_at=None,
        ingested_at=available_at.astimezone(UTC),
        source_revision=1,
        adapter_version=f"{provider}-adapter-v1",
        normalization_version=f"{provider}-normalization-v1",
        freshness_policy_version=f"{provider}-freshness-v1",
        request_identity=request_identity,
        plan_hash=plan_hash,
        checkpoint_reference=(
            checkpoint_reference
            or f"storage/test/{provider.lower()}/response.bin"
        ),
    )


def _event_hash(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    ).hexdigest().upper()


def write_source_receipt_v1(
    root: Path,
    payload: dict[str, object],
    provider: str,
    available_at: datetime,
    *,
    symbol: str,
    identity: ProjectedIdentityMemberV2,
    projection_content_hash: str,
    source_kind: str = "FUNDAMENTALS",
):
    if source_kind == "FUNDAMENTALS":
        raw = json.dumps(payload, sort_keys=True).encode("utf-8")
        execution_version = "FV-CURRENT-FUNDAMENTALS-EXECUTION-v1.0.0"
        run_id = f"TEST-FUNDAMENTALS-{symbol}"
        endpoint_path = f"/api/fundamentals/{symbol}.US?fmt=json"
        request_body = {
            "executionVersion": execution_version,
            "runId": run_id,
            "ordinal": identity.ordinal,
            "symbol": symbol,
            "securityId": identity.security_id,
            "endpointPath": endpoint_path,
            "preflightSealedAt": available_at.isoformat().replace("+00:00", "Z"),
            "configuredWeight": 10,
        }
        configured_weight = 10
    elif source_kind == "PRICE" and provider == "EODHD":
        rows = []
        for bar in payload["bars"]:
            raw_price = bar["raw"]
            rows.append(
                {
                    "date": bar["tradingDate"],
                    "open": raw_price["open"],
                    "high": raw_price["high"],
                    "low": raw_price["low"],
                    "close": raw_price["close"],
                    "adjusted_close": raw_price["adjustedClose"],
                    "volume": bar["volume"],
                }
            )
        raw = json.dumps(rows, sort_keys=True).encode("utf-8")
        execution_version = "FV-CURRENT-ASSESSMENT-EXECUTION-v1.0.0"
        run_id = f"TEST-PRICE-{symbol}"
        end_date = max(
            date.fromisoformat(str(bar["tradingDate"])) for bar in payload["bars"]
        )
        start_date = end_date - timedelta(days=14)
        endpoint_path = (
            f"/api/eod/{symbol}.US?fmt=json&from={start_date.isoformat()}"
            f"&to={end_date.isoformat()}&period=d"
        )
        request_body = {
            "executionVersion": execution_version,
            "planRunId": run_id,
            "ordinal": identity.ordinal,
            "symbol": symbol,
            "securityId": identity.security_id,
            "companyId": identity.company_id,
            "instrumentId": identity.instrument_id,
            "shareClassId": identity.share_class_id,
            "listingId": identity.listing_id,
            "tickerAssignmentId": identity.ticker_assignment_id,
            "mic": identity.mic,
            "currency": identity.currency,
            "priceProvider": "EODHD_EOD",
            "endpointPath": endpoint_path,
            "preflightSealedAt": available_at.isoformat().replace("+00:00", "Z"),
        }
        configured_weight = 1
    else:
        raise ValueError("unsupported synthetic receipt kind")
    request_identity = _event_hash(request_body)
    endpoint_category = "fundamentals" if source_kind == "FUNDAMENTALS" else "EODHD_EOD"
    request = {
        "ordinal": identity.ordinal,
        "symbol": symbol,
        "security_id": identity.security_id,
        "endpoint_path": endpoint_path,
        "request_identity": request_identity,
    }
    if source_kind == "FUNDAMENTALS":
        request["configured_weight"] = configured_weight
    else:
        request["mic"] = identity.mic
    plan_body = {
        "executionVersion": execution_version,
        "runId": run_id,
        "preflightSealedAt": available_at.isoformat().replace("+00:00", "Z"),
        "identityProjectionContentHash": projection_content_hash,
        "requests": [request],
        "networkAuthorized": True,
        "retryLimit": 0,
        "physicalRequestCeiling": 3,
    }
    if source_kind == "FUNDAMENTALS":
        plan_body["configuredWeightCeiling"] = 30
    else:
        plan_body.update(
            {
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "priceProvider": "EODHD_EOD",
            }
        )
    plan_hash = _event_hash(plan_body)
    response_hash = hashlib.sha256(raw).hexdigest().upper()
    outer_run = root / run_id
    request_dir = outer_run / "journals" / run_id / "requests" / symbol / request_identity
    checkpoint = request_dir / "responses" / f"{response_hash}.bin"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_bytes(raw)
    attempt_id = f"{request_identity}:1"
    events = (
        {
            "schemaVersion": "physical-request-journal-v1.0.0",
            "eventType": "PHYSICAL_REQUEST",
            "runId": run_id,
            "symbol": symbol,
            "requestIdentity": request_identity,
            "sequence": 1,
            "state": "INTENT",
            "detail": {
                "endpointCategory": endpoint_category,
                "attemptId": attempt_id,
                "configuredWeight": configured_weight,
                "startedAt": available_at.isoformat(),
            },
        },
        {
            "schemaVersion": "physical-request-journal-v1.0.0",
            "eventType": "PHYSICAL_REQUEST",
            "runId": run_id,
            "symbol": symbol,
            "requestIdentity": request_identity,
            "sequence": 2,
            "state": "COMPLETED",
            "detail": {
                "endpointCategory": endpoint_category,
                "attemptId": attempt_id,
                "configuredWeight": configured_weight,
                "durationMs": 1,
                "status": 200,
                "headers": {"date": format_datetime(available_at, usegmt=True)},
                "responseCheckpointPath": str(checkpoint.resolve()),
                "responseContentHash": response_hash,
            },
        },
    )
    for event in events:
        sealed = {**event, "eventHash": _event_hash(event)}
        path = request_dir / f"{event['sequence']:06d}-{event['state']}.json"
        path.write_text(json.dumps(sealed, indent=2) + "\n", encoding="utf-8")
    preflight = {
        "schemaVersion": "physical-request-journal-v1.0.0",
        "eventType": "RUN",
        "runId": run_id,
        "sequence": 1,
        "state": "PREFLIGHT",
        "detail": {"sliceId": plan_hash, "symbols": [symbol]},
    }
    preflight["eventHash"] = _event_hash(preflight)
    run_dir = outer_run / "journals" / run_id / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "000001-PREFLIGHT.json").write_text(
        json.dumps(preflight, indent=2) + "\n", encoding="utf-8"
    )
    (outer_run / "plan.json").write_text(
        json.dumps({**plan_body, "planHash": plan_hash}, indent=2) + "\n",
        encoding="utf-8",
    )
    relative = str(checkpoint.resolve().relative_to(root.resolve()))
    return raw, source_seal_from_bytes_v1(
        provider_code=provider,
        schema_version=(
            "EODHD-CURRENT-FUNDAMENTALS-CAPTURE-v1.0.0"
            if source_kind == "FUNDAMENTALS"
            else "FV-CURRENT-EODHD-PRICE-NORMALIZATION-v1.0.0"
        ),
        source_reference=f"private://{provider.lower()}/{symbol}/{source_kind.lower()}",
        raw=raw,
        canonical_payload=payload,
        available_at=available_at,
        retrieved_at=None,
        ingested_at=available_at,
        source_revision=1,
        adapter_version=(
            "EODHD-CURRENT-FUNDAMENTALS-ADAPTER-v1.0.0"
            if source_kind == "FUNDAMENTALS"
            else "FV-CURRENT-EODHD-PRICE-ADAPTER-v1.0.0"
        ),
        normalization_version=(
            "EODHD-CURRENT-FUNDAMENTALS-NORMALIZATION-v1.0.0"
            if source_kind == "FUNDAMENTALS"
            else "FV-CURRENT-EODHD-PRICE-NORMALIZATION-v1.0.0"
        ),
        freshness_policy_version=(
            "FV-CURRENT-FUNDAMENTALS-180D-v1.0.0"
            if source_kind == "FUNDAMENTALS"
            else "FV-CURRENT-PRICE-5D-v1.0.0"
        ),
        request_identity=request_identity,
        plan_hash=plan_hash,
        checkpoint_reference=relative,
    )


def seed_synthetic_current_identity_authority_v25(
    database_url: str,
    *,
    ticker: str = "GOOG",
) -> tuple[ProjectedIdentityMemberV2, str]:
    """Install and return the deterministic TEST_ONLY V25 identity authority."""

    if ticker not in {"GOOG", "FOX", "MSFT"}:
        raise ValueError("unsupported synthetic identity ticker")
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) AS value FROM analytics.fv_identity_authority_v2 "
                "WHERE authority_id=%s",
                (_SYNTHETIC_AUTHORITY_ID,),
            )
            if cursor.fetchone()["value"] == 0:
                cursor.execute(
                    "SELECT public_id::text AS public_id FROM analytics.security "
                    "WHERE symbol='MSFT'"
                )
                msft_security = cursor.fetchone()["public_id"]
                cursor.execute(
                    """INSERT INTO analytics.security (
                         public_id,symbol,exchange,name,instrument_type,currency,active
                       ) VALUES
                         (%s,'GOOG','XNAS','Alphabet Inc.','COMMON_STOCK','USD',true),
                         (%s,'FOX','XNAS','Fox Corp','COMMON_STOCK','USD',true)""",
                    (_SYNTHETIC_GOOG[0], _SYNTHETIC_FOX[0]),
                )
                cursor.execute(
                    """INSERT INTO analytics.fv_identity_authority_v2 (
                      authority_id,contract_version,authority_version,registry_version,
                      inventory_as_of_date,evidence_claim,model_evidence_label,
                      openfigi_result_hash,openfigi_review_hash,sec_result_hash,
                      sec_acceptance_hash,sec_review_hash,inventory_authorization_hash,
                      inventory_review_hash,inventory_receipt_hash,projection_content_hash,
                      member_set_hash,member_count,v22_write_authorized,
                      v24_enrollment_authorized,investment_assessment_authorized,
                      evidence_label_upgrade_authorized,idempotency_key,revision,
                      supersedes_authority_id
                    ) VALUES (
                      %s,'FV-STAGE8C-FORWARD-IDENTITY-PROJECTION-v2.0.0',
                      'FV-STAGE8C-IDENTITY-AUTHORITY-v1.0.0',
                      'security-identity-registry-v1.0.0',DATE '2026-08-02',
                      'ENGINEERING_IDENTITY_AUTHORITY_ONLY','NOT_VALIDATED',
                      'AD83ACD175AFA01D706D689EE48B93233BB8D95D6B494655B7E15337B5FDC6B7',
                      'E53CF93A88523B8F91F5F84AB59FD230F5335E218970B87FB77321BF1AA57747',
                      '826041EEBFFF3C135DBC6C5154E3CB7F8F0B0D9F6FBCB797549DF1A57DB50050',
                      'FF4286FBC31CB413BF92C3ECBBDC618F7913E80622CC211A4B46E8A16EFB169A',
                      '8060C22C1D911BF6108A9AD0BB407EED80B81CE6E2089C45AF4F3A19398E4745',
                      '6AC4E9A95F727AA6D96850771F52A610662D0C96DBDF8C56D1CFFFC97DDE2C3D',
                      '8AC0DC15E6D0FABC89C2F42DC1D7D929F0AF54C6FB4F37803849F81740ED5FCE',
                      'F1BEDECEE6343F4CC7D0F4C674066C75F44EE6DA979C61EB799B4D068667776B',
                      'sha256:'||repeat('1',64),'sha256:'||repeat('2',64),3,
                      true,false,false,false,'FV-STAGE8C-V26-TYPED-001',1,NULL)""",
                    (_SYNTHETIC_AUTHORITY_ID,),
                )
                member_rows = (
                    (
                        1,
                        "GOOG",
                        *_SYNTHETIC_GOOG,
                        "NEW_ID_CANDIDATE",
                        None,
                        "Alphabet Inc.",
                        "1652044",
                        "US02079K1079",
                        "02079K107",
                        "BBG009S3NB30",
                        "BBG009S3NB30",
                        "BBG009S3NB21",
                        "A",
                        "a",
                        "b",
                        "c",
                        "d",
                    ),
                    (
                        2,
                        "FOX",
                        *_SYNTHETIC_FOX,
                        "NEW_ID_CANDIDATE",
                        None,
                        "Fox Corp",
                        "1754301",
                        "US35137L2043",
                        "35137L204",
                        "BBG00JHNKJY8",
                        "BBG00JHNKJY8",
                        "BBG00JHNKKR3",
                        "B",
                        "e",
                        "f",
                        "0",
                        "1",
                    ),
                    (
                        3,
                        "MSFT",
                        msft_security,
                        *_SYNTHETIC_MSFT[1:],
                        "ADOPT_EXISTING_PUBLIC_ID_V22_GRAPH_REQUIRED",
                        msft_security,
                        "Microsoft Corporation",
                        "789019",
                        "US5949181045",
                        "594918104",
                        "BBG000BPH459",
                        "BBG000BPH459",
                        "BBG001S5TD05",
                        "C",
                        "2",
                        "3",
                        "4",
                        "5",
                    ),
                )
                for row in member_rows:
                    (
                        ordinal,
                        member_ticker,
                        security_id,
                        company_id,
                        instrument_id,
                        share_class_id,
                        listing_id,
                        ticker_assignment_id,
                        adoption,
                        existing_id,
                        company_name,
                        cik,
                        isin,
                        cusip,
                        figi,
                        composite_figi,
                        share_figi,
                        provider_digit,
                        source_digit,
                        sec_digit,
                        decision_digit,
                        member_digit,
                    ) = row
                    cursor.execute(
                        """INSERT INTO analytics.fv_identity_authority_member_v2 (
                          authority_id,member_ordinal,ticker,security_id,company_id,
                          instrument_id,share_class_id,listing_id,ticker_assignment_id,
                          adoption_state,existing_public_id,company_name,sec_cik,mic,
                          currency,instrument_type,ticker_valid_from,isin,cusip,figi,
                          composite_figi,share_class_figi,openfigi_provider_identity_hash,
                          openfigi_source_hash,sec_source_hash,inventory_decision_hash,
                          member_content_hash
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'XNAS',
                          'USD','COMMON_STOCK',DATE '2026-08-02',%s,%s,%s,%s,%s,
                          repeat(%s,64),'sha256:'||repeat(%s,64),
                          'sha256:'||repeat(%s,64),'sha256:'||repeat(%s,64),
                          'sha256:'||repeat(%s,64))""",
                        (
                            _SYNTHETIC_AUTHORITY_ID,
                            ordinal,
                            member_ticker,
                            security_id,
                            company_id,
                            instrument_id,
                            share_class_id,
                            listing_id,
                            ticker_assignment_id,
                            adoption,
                            existing_id,
                            company_name,
                            cik,
                            isin,
                            cusip,
                            figi,
                            composite_figi,
                            share_figi,
                            provider_digit,
                            source_digit,
                            sec_digit,
                            decision_digit,
                            member_digit,
                        ),
                    )
                    cursor.execute(
                        "INSERT INTO analytics.evidence_company_identity_v1 VALUES "
                        "(%s,'security-identity-registry-v1.0.0',CURRENT_TIMESTAMP)",
                        (company_id,),
                    )
                    cursor.execute(
                        "INSERT INTO analytics.evidence_instrument_identity_v1 VALUES "
                        "(%s,%s,'security-identity-registry-v1.0.0',CURRENT_TIMESTAMP)",
                        (instrument_id, company_id),
                    )
                    cursor.execute(
                        "INSERT INTO analytics.evidence_share_class_identity_v1 VALUES "
                        "(%s,%s,'security-identity-registry-v1.0.0',CURRENT_TIMESTAMP)",
                        (share_class_id, instrument_id),
                    )
                    cursor.execute(
                        "INSERT INTO analytics.evidence_listing_identity_v1 VALUES "
                        "(%s,%s,%s,'XNAS','USD','security-identity-registry-v1.0.0',"
                        "CURRENT_TIMESTAMP)",
                        (listing_id, share_class_id, security_id),
                    )
                    cursor.execute(
                        "INSERT INTO analytics.evidence_ticker_assignment_v1 VALUES "
                        "(%s,%s,%s,DATE '2026-08-02',NULL,"
                        "'security-identity-registry-v1.0.0',CURRENT_TIMESTAMP)",
                        (ticker_assignment_id, listing_id, member_ticker),
                    )
                cursor.execute(
                    """INSERT INTO analytics.fv_identity_authority_seal_v2 (
                       authority_id,projection_content_hash,member_set_hash,
                       member_count,seal_content_hash,creator_xid8
                    ) VALUES (%s,'sha256:'||repeat('1',64),
                       'sha256:'||repeat('2',64),3,
                       'sha256:'||repeat('6',64),'1'::xid8)""",
                    (_SYNTHETIC_AUTHORITY_ID,),
                )
            cursor.execute(
                """SELECT authority.projection_content_hash,
                          member.member_ordinal AS ordinal,member.ticker,
                          member.security_id::text AS security_id,
                          member.company_id::text AS company_id,
                          member.instrument_id::text AS instrument_id,
                          member.share_class_id::text AS share_class_id,
                          member.listing_id::text AS listing_id,
                          member.ticker_assignment_id::text AS ticker_assignment_id,
                          member.adoption_state,
                          member.existing_public_id::text AS existing_public_id,
                          member.company_name,member.sec_cik,member.mic,member.currency,
                          member.instrument_type,member.ticker_valid_from::text,
                          member.isin,member.cusip,member.figi,member.composite_figi,
                          member.share_class_figi,member.openfigi_provider_identity_hash,
                          member.openfigi_source_hash,member.sec_source_hash,
                          member.inventory_decision_hash,
                          member.member_content_hash AS content_hash
                   FROM analytics.fv_identity_authority_v2 authority
                   JOIN analytics.fv_identity_authority_member_v2 member
                     ON member.authority_id=authority.authority_id
                   WHERE authority.authority_id=%s AND member.ticker=%s""",
                (_SYNTHETIC_AUTHORITY_ID, ticker),
            )
            durable = cursor.fetchone()
    if durable is None:
        raise AssertionError("synthetic V25 identity authority is missing")
    projection_content_hash = durable.pop("projection_content_hash")
    return ProjectedIdentityMemberV2(**durable), projection_content_hash


__all__ = [
    "fundamentals_fixture_v1",
    "eodhd_price_fixture_v1",
    "price_fixture_v1",
    "seed_synthetic_current_identity_authority_v25",
    "source_fixture_v1",
    "write_source_receipt_v1",
]
