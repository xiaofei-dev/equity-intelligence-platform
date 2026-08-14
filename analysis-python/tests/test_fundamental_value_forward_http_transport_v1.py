from __future__ import annotations

import hashlib
import inspect
import ssl
from dataclasses import replace
from email.message import Message
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from equity_analysis.fundamental_value import (
    prospective_company_quality_http_transport_v1 as http_transport_module,
)
from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    PARSER_REGISTRY_CONTENT_HASH,
    ProviderWireRequest,
)
from equity_analysis.fundamental_value.prospective_company_quality_http_transport_v1 import (
    PRODUCTION_TRANSPORT_VERSION,
    HttpTransportBoundaryError,
    StdlibAcquisitionHttpTransport,
    TestOnlyStdlibAcquisitionHttpTransport,
)

_DATE = "Sun, 02 Aug 2026 12:00:00 GMT"
_SEC_CONTACT = "Equity Intelligence Platform engineering@example.com"
_EODHD_PLACEHOLDER = "unit-test-placeholder"


class _FakeResponse:
    def __init__(
        self,
        *,
        url: str,
        status: int = 200,
        body: bytes = b"{}",
        headers: tuple[tuple[str, str], ...] = (("Date", _DATE),),
        close_error: BaseException | None = None,
    ) -> None:
        self.status = status
        self._url = url
        self._body = body
        self.headers = Message()
        for name, value in headers:
            self.headers[name] = value
        self.closed = False
        self._close_error = close_error

    def read(self, amount: int) -> bytes:
        return self._body[:amount]

    def geturl(self) -> str:
        return self._url

    def close(self) -> None:
        self.closed = True
        if self._close_error is not None:
            raise self._close_error


class _FakeOpener:
    def __init__(self, actions: tuple[object, ...]) -> None:
        self._actions = list(actions)
        self.calls: list[tuple[Request, float]] = []

    def open(self, request: Request, *, timeout: float):
        self.calls.append((request, timeout))
        action = self._actions.pop(0)
        if isinstance(action, BaseException):
            raise action
        return action


class _CloseAttributeFailureResponse(_FakeResponse):
    @property
    def close(self):
        raise RuntimeError(f"sensitive {_EODHD_PLACEHOLDER} close lookup failure")


def _wire(
    provider: str,
    path: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    headers: tuple[tuple[str, str], ...] = (("accept", "application/json"),),
) -> ProviderWireRequest:
    return ProviderWireRequest(
        request_identity=f"REQUEST-{provider}",
        provider=provider,
        method=method,
        endpoint_path=path,
        headers=headers,
        body=body,
        body_sha256=(
            hashlib.sha256(body).hexdigest().upper() if body is not None else None
        ),
    )


def _request_headers(request: Request) -> dict[str, str]:
    return {name.lower(): value for name, value in request.header_items()}


def test_constructor_performs_no_io_and_binds_parser_registry() -> None:
    opener = _FakeOpener(())

    transport = TestOnlyStdlibAcquisitionHttpTransport(opener=opener)

    assert opener.calls == []
    assert transport.test_only is True
    assert transport.transport_kind == "TEST_ONLY"
    assert transport.parser_registry_content_hash == PARSER_REGISTRY_CONTENT_HASH
    assert transport.transport_contract_version == PRODUCTION_TRANSPORT_VERSION
    assert transport.proxy_policy == "ENVIRONMENT_PROXIES_DISABLED"
    assert transport.retry_limit == 0


def test_production_transport_has_exact_attestation_and_no_opener_surface() -> None:
    signature = inspect.signature(StdlibAcquisitionHttpTransport.__init__)

    assert "opener" not in signature.parameters
    assert "factory" not in signature.parameters
    with pytest.raises(TypeError):
        StdlibAcquisitionHttpTransport(opener=_FakeOpener(()))  # type: ignore[call-arg]

    transport = StdlibAcquisitionHttpTransport()
    assert type(transport) is StdlibAcquisitionHttpTransport
    assert transport.test_only is False
    assert transport.transport_kind == "PRODUCTION"
    assert transport.transport_contract_version == PRODUCTION_TRANSPORT_VERSION
    assert transport.transport_version == PRODUCTION_TRANSPORT_VERSION
    assert transport.parser_registry_content_hash == PARSER_REGISTRY_CONTENT_HASH
    assert transport.proxy_policy == "ENVIRONMENT_PROXIES_DISABLED"
    assert transport.retry_limit == 0
    assert not hasattr(transport, "_opener")
    assert not hasattr(transport, "_test_opener")


def test_production_transport_does_not_store_or_reveal_eodhd_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    variable = "STAGE8C_TEST_EODHD_KEY"
    monkeypatch.setenv(variable, _EODHD_PLACEHOLDER)

    transport = StdlibAcquisitionHttpTransport(
        eodhd_api_key_environment_variable=variable
    )

    assert _EODHD_PLACEHOLDER not in repr(transport)
    assert not hasattr(transport, "_eodhd_api_key")
    for name in dir(transport):
        value = getattr(transport, name)
        assert value != _EODHD_PLACEHOLDER


def test_production_construction_does_not_read_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        http_transport_module,
        "_read_environment_value",
        lambda _name: (_ for _ in ()).throw(
            AssertionError("environment must not be read during construction")
        ),
    )

    transport = StdlibAcquisitionHttpTransport()

    assert type(transport) is StdlibAcquisitionHttpTransport


def test_production_dispatch_builds_only_frozen_internal_opener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = "/v3/mapping"
    response = _FakeResponse(url="https://api.openfigi.com" + path, body=b"[]")
    opener = _FakeOpener((response,))
    observed_handlers: list[tuple[object, ...]] = []

    def frozen_builder(*handlers: object) -> _FakeOpener:
        observed_handlers.append(handlers)
        return opener

    monkeypatch.setattr(http_transport_module, "build_opener", frozen_builder)
    transport = StdlibAcquisitionHttpTransport()
    wire = _wire(
        "OPENFIGI",
        path,
        method="POST",
        body=b"[]",
        headers=(
            ("accept", "application/json"),
            ("content-type", "application/json"),
        ),
    )

    result = transport.send(wire)

    assert result.status_code == 200
    assert len(observed_handlers) == 1
    proxy, redirect = observed_handlers[0]
    assert type(proxy) is http_transport_module.ProxyHandler
    assert proxy.proxies == {}
    assert type(redirect) is http_transport_module._NoRedirectHandler
    assert len(opener.calls) == 1


def test_production_environment_read_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        http_transport_module,
        "_read_environment_value",
        lambda _name: (_ for _ in ()).throw(
            OSError(f"sensitive {_EODHD_PLACEHOLDER} environment failure")
        ),
    )
    transport = StdlibAcquisitionHttpTransport()

    with pytest.raises(HttpTransportBoundaryError) as caught:
        transport.send(_wire("EODHD", "/api/fundamentals/MSFT.US?fmt=json"))

    assert str(caught.value) == "HTTP_TRANSPORT_UNKNOWN"
    assert _EODHD_PLACEHOLDER not in str(caught.value)
    assert _EODHD_PLACEHOLDER not in repr(caught.value)


@pytest.mark.parametrize(
    ("provider", "path", "origin"),
    (
        ("SEC", "/files/company_tickers_exchange.json", "https://www.sec.gov"),
        (
            "YAHOO_CHART",
            "/v8/finance/chart/MSFT?range=10d&interval=1d"
            "&events=div%2Csplits&includeAdjustedClose=true",
            "https://query1.finance.yahoo.com",
        ),
    ),
)
def test_get_providers_use_exact_allowlisted_origin(
    provider: str, path: str, origin: str
) -> None:
    response = _FakeResponse(url=origin + path)
    opener = _FakeOpener((response,))
    transport = TestOnlyStdlibAcquisitionHttpTransport(
        sec_user_agent_contact=_SEC_CONTACT,
        opener=opener,
    )

    result = transport.send(_wire(provider, path))

    outgoing, timeout = opener.calls[0]
    assert outgoing.full_url == origin + path
    assert outgoing.get_method() == "GET"
    assert outgoing.data is None
    assert timeout == 20.0
    assert result.status_code == 200
    if provider == "SEC":
        assert _request_headers(outgoing)["user-agent"] == _SEC_CONTACT
    assert response.closed is True


def test_openfigi_post_preserves_body_and_exact_origin() -> None:
    body = b'[{"idType":"ID_ISIN","idValue":"US5949181045"}]'
    path = "/v3/mapping"
    response = _FakeResponse(url="https://api.openfigi.com" + path, body=b"[]")
    opener = _FakeOpener((response,))
    transport = TestOnlyStdlibAcquisitionHttpTransport(opener=opener)
    wire = _wire(
        "OPENFIGI",
        path,
        method="POST",
        body=body,
        headers=(
            ("accept", "application/json"),
            ("content-type", "application/json"),
        ),
    )

    transport.send(wire)

    outgoing, _timeout = opener.calls[0]
    assert outgoing.full_url == "https://api.openfigi.com/v3/mapping"
    assert outgoing.get_method() == "POST"
    assert outgoing.data == body
    assert _request_headers(outgoing)["content-type"] == "application/json"


def test_eodhd_secret_is_injected_only_at_dispatch_and_never_returned() -> None:
    path = "/api/fundamentals/MSFT.US?fmt=json"
    expected_url = (
        "https://eodhd.com/api/fundamentals/MSFT.US?fmt=json"
        f"&api_token={_EODHD_PLACEHOLDER}"
    )
    response = _FakeResponse(
        url=expected_url,
        headers=(("Date", _DATE), ("X-RateLimit-Remaining", "98765")),
    )
    opener = _FakeOpener((response,))
    transport = TestOnlyStdlibAcquisitionHttpTransport(
        eodhd_api_key=_EODHD_PLACEHOLDER,
        opener=opener,
    )
    wire = _wire("EODHD", path)

    result = transport.send(wire)

    outgoing, _timeout = opener.calls[0]
    assert wire.endpoint_path == path
    assert _EODHD_PLACEHOLDER not in repr(wire)
    assert outgoing.full_url == expected_url
    assert _EODHD_PLACEHOLDER not in repr(transport)
    assert _EODHD_PLACEHOLDER not in repr(result)
    assert result.headers == (
        ("date", _DATE),
        ("x-ratelimit-remaining", "98765"),
    )


def test_eodhd_requires_key_only_when_dispatched() -> None:
    opener = _FakeOpener(())
    transport = TestOnlyStdlibAcquisitionHttpTransport(opener=opener)

    with pytest.raises(HttpTransportBoundaryError, match="^EODHD_API_KEY_REQUIRED$"):
        transport.send(_wire("EODHD", "/api/fundamentals/MSFT.US?fmt=json"))

    assert opener.calls == []


def test_sec_requires_contact_only_when_dispatched() -> None:
    opener = _FakeOpener(())
    transport = TestOnlyStdlibAcquisitionHttpTransport(opener=opener)

    with pytest.raises(
        HttpTransportBoundaryError, match="^SEC_USER_AGENT_CONTACT_REQUIRED$"
    ):
        transport.send(_wire("SEC", "/files/company_tickers_exchange.json"))

    assert opener.calls == []


@pytest.mark.parametrize("status", (400, 401, 403, 429, 500, 503))
def test_http_error_is_returned_for_existing_status_classifier(status: int) -> None:
    path = "/v3/mapping"
    url = "https://api.openfigi.com" + path
    headers = Message()
    headers["Date"] = _DATE
    error = HTTPError(
        url, status, "provider error", headers, BytesIO(b'{"error":"x"}')
    )
    opener = _FakeOpener((error,))
    transport = TestOnlyStdlibAcquisitionHttpTransport(opener=opener)
    wire = _wire(
        "OPENFIGI",
        path,
        method="POST",
        body=b"[]",
        headers=(
            ("accept", "application/json"),
            ("content-type", "application/json"),
        ),
    )

    result = transport.send(wire)

    assert result.status_code == status
    assert result.body == b'{"error":"x"}'


@pytest.mark.parametrize("status", (301, 302, 307, 308))
def test_redirect_status_is_never_followed(status: int) -> None:
    path = "/files/company_tickers_exchange.json"
    response = _FakeResponse(
        url="https://attacker.invalid/redirected",
        status=status,
    )
    opener = _FakeOpener((response,))
    transport = TestOnlyStdlibAcquisitionHttpTransport(
        sec_user_agent_contact=_SEC_CONTACT,
        opener=opener,
    )

    with pytest.raises(HttpTransportBoundaryError, match="^HTTP_REDIRECT_BLOCKED$"):
        transport.send(_wire("SEC", path))

    assert len(opener.calls) == 1


def test_urllib_redirect_http_error_is_sanitized_and_not_returned() -> None:
    path = "/files/company_tickers_exchange.json"
    url = "https://www.sec.gov" + path
    headers = Message()
    headers["Location"] = "https://attacker.invalid/redirected"
    error = HTTPError(url, 302, "redirect", headers, BytesIO(b"redirect"))
    opener = _FakeOpener((error,))
    transport = TestOnlyStdlibAcquisitionHttpTransport(
        sec_user_agent_contact=_SEC_CONTACT,
        opener=opener,
    )

    with pytest.raises(HttpTransportBoundaryError, match="^HTTP_REDIRECT_BLOCKED$"):
        transport.send(_wire("SEC", path))

    assert len(opener.calls) == 1


def test_malformed_http_error_status_is_sanitized() -> None:
    path = "/files/company_tickers_exchange.json"
    url = "https://www.sec.gov" + path
    error = HTTPError(url, "401", "malformed", Message(), BytesIO(b"error"))
    opener = _FakeOpener((error,))
    transport = TestOnlyStdlibAcquisitionHttpTransport(
        sec_user_agent_contact=_SEC_CONTACT,
        opener=opener,
    )

    with pytest.raises(
        HttpTransportBoundaryError, match="^HTTP_RESPONSE_STATUS_INVALID$"
    ):
        transport.send(_wire("SEC", path))


def test_cross_host_final_response_is_rejected() -> None:
    path = "/files/company_tickers_exchange.json"
    response = _FakeResponse(url="https://attacker.invalid" + path)
    transport = TestOnlyStdlibAcquisitionHttpTransport(
        sec_user_agent_contact=_SEC_CONTACT,
        opener=_FakeOpener((response,)),
    )

    with pytest.raises(
        HttpTransportBoundaryError, match="^HTTP_RESPONSE_TARGET_DRIFT$"
    ):
        transport.send(_wire("SEC", path))


def test_body_ceiling_fails_closed_without_truncation() -> None:
    path = "/v3/mapping"
    response = _FakeResponse(
        url="https://api.openfigi.com" + path,
        body=b"12345",
    )
    transport = TestOnlyStdlibAcquisitionHttpTransport(
        max_response_body_bytes=4,
        opener=_FakeOpener((response,)),
    )
    wire = _wire(
        "OPENFIGI",
        path,
        method="POST",
        body=b"[]",
        headers=(
            ("accept", "application/json"),
            ("content-type", "application/json"),
        ),
    )

    with pytest.raises(
        HttpTransportBoundaryError, match="^HTTP_RESPONSE_BODY_TOO_LARGE$"
    ):
        transport.send(wire)


def test_only_required_headers_are_retained() -> None:
    path = "/files/company_tickers_exchange.json"
    response = _FakeResponse(
        url="https://www.sec.gov" + path,
        headers=(
            ("Server", "ignored"),
            ("Content-Type", "application/json"),
            ("Date", _DATE),
        ),
    )
    transport = TestOnlyStdlibAcquisitionHttpTransport(
        sec_user_agent_contact=_SEC_CONTACT,
        opener=_FakeOpener((response,)),
    )

    result = transport.send(_wire("SEC", path))

    assert result.headers == (
        ("content-type", "application/json"),
        ("date", _DATE),
    )


def test_exact_canonical_response_header_allowlist_is_retained() -> None:
    path = "/files/company_tickers_exchange.json"
    selected = (
        ("Content-Type", "application/json"),
        ("Date", _DATE),
        ("RateLimit-Limit", "25"),
        ("RateLimit-Remaining", "24"),
        ("RateLimit-Reset", "60"),
        ("Retry-After", "2"),
        ("X-RateLimit-Limit", "25"),
        ("X-RateLimit-Remaining", "24"),
        ("X-RateLimit-Reset", "60"),
    )
    response = _FakeResponse(
        url="https://www.sec.gov" + path,
        headers=selected + (("Server", "ignored"),),
    )
    transport = TestOnlyStdlibAcquisitionHttpTransport(
        sec_user_agent_contact=_SEC_CONTACT,
        opener=_FakeOpener((response,)),
    )

    result = transport.send(_wire("SEC", path))

    assert result.headers == tuple(
        sorted((name.lower(), value) for name, value in selected)
    )


def test_duplicate_required_response_header_is_rejected() -> None:
    path = "/files/company_tickers_exchange.json"
    response = _FakeResponse(
        url="https://www.sec.gov" + path,
        headers=(("Date", _DATE), ("date", _DATE)),
    )
    transport = TestOnlyStdlibAcquisitionHttpTransport(
        sec_user_agent_contact=_SEC_CONTACT,
        opener=_FakeOpener((response,)),
    )

    with pytest.raises(
        HttpTransportBoundaryError, match="^HTTP_RESPONSE_HEADER_DUPLICATE$"
    ):
        transport.send(_wire("SEC", path))


@pytest.mark.parametrize(
    "raised",
    (
        URLError("unit-test-placeholder-host"),
        TimeoutError("unit-test-placeholder-timeout"),
        ssl.SSLError("unit-test-placeholder-tls"),
    ),
)
def test_transport_exceptions_are_sanitized(raised: BaseException) -> None:
    opener = _FakeOpener((raised,))
    transport = TestOnlyStdlibAcquisitionHttpTransport(
        eodhd_api_key=_EODHD_PLACEHOLDER,
        opener=opener,
    )

    with pytest.raises(HttpTransportBoundaryError) as caught:
        transport.send(_wire("EODHD", "/api/fundamentals/MSFT.US?fmt=json"))

    assert str(caught.value) == "HTTP_TRANSPORT_UNKNOWN"
    assert _EODHD_PLACEHOLDER not in str(caught.value)
    assert _EODHD_PLACEHOLDER not in repr(caught.value)


def test_eodhd_secret_reflection_is_blocked() -> None:
    path = "/api/fundamentals/MSFT.US?fmt=json"
    url = (
        "https://eodhd.com/api/fundamentals/MSFT.US?fmt=json"
        f"&api_token={_EODHD_PLACEHOLDER}"
    )
    response = _FakeResponse(url=url, body=_EODHD_PLACEHOLDER.encode("ascii"))
    transport = TestOnlyStdlibAcquisitionHttpTransport(
        eodhd_api_key=_EODHD_PLACEHOLDER,
        opener=_FakeOpener((response,)),
    )

    with pytest.raises(
        HttpTransportBoundaryError, match="^EODHD_SECRET_REFLECTION_BLOCKED$"
    ):
        transport.send(_wire("EODHD", path))


def test_response_close_failure_is_sanitized_without_secret_leakage() -> None:
    path = "/api/fundamentals/MSFT.US?fmt=json"
    url = (
        "https://eodhd.com/api/fundamentals/MSFT.US?fmt=json"
        f"&api_token={_EODHD_PLACEHOLDER}"
    )
    response = _FakeResponse(
        url=url,
        close_error=RuntimeError(f"sensitive {_EODHD_PLACEHOLDER} close failure"),
    )
    transport = TestOnlyStdlibAcquisitionHttpTransport(
        eodhd_api_key=_EODHD_PLACEHOLDER,
        opener=_FakeOpener((response,)),
    )

    with pytest.raises(HttpTransportBoundaryError) as caught:
        transport.send(_wire("EODHD", path))

    assert str(caught.value) == "HTTP_RESPONSE_CLOSE_FAILED"
    assert _EODHD_PLACEHOLDER not in str(caught.value)
    assert _EODHD_PLACEHOLDER not in repr(caught.value)


def test_response_close_attribute_failure_is_sanitized() -> None:
    path = "/api/fundamentals/MSFT.US?fmt=json"
    url = (
        "https://eodhd.com/api/fundamentals/MSFT.US?fmt=json"
        f"&api_token={_EODHD_PLACEHOLDER}"
    )
    response = _CloseAttributeFailureResponse(url=url)
    transport = TestOnlyStdlibAcquisitionHttpTransport(
        eodhd_api_key=_EODHD_PLACEHOLDER,
        opener=_FakeOpener((response,)),
    )

    with pytest.raises(HttpTransportBoundaryError) as caught:
        transport.send(_wire("EODHD", path))

    assert str(caught.value) == "HTTP_RESPONSE_CLOSE_FAILED"
    assert _EODHD_PLACEHOLDER not in str(caught.value)


@pytest.mark.parametrize(
    "wire",
    (
        _wire(
            "OPENFIGI",
            "/v3/mapping",
            method="POST",
            body=b"[]",
            headers=(
                ("accept", "application/json"),
                ("content-type", "application/json"),
                ("authorization", "injected"),
            ),
        ),
        _wire(
            "SEC",
            "/files/company_tickers_exchange.json",
            headers=(("accept", "application/json\r\nX-Injected: yes"),),
        ),
        _wire("SEC", "https://attacker.invalid/files/company_tickers_exchange.json"),
    ),
)
def test_request_header_and_target_injection_are_rejected_before_io(
    wire: ProviderWireRequest,
) -> None:
    opener = _FakeOpener(())
    transport = TestOnlyStdlibAcquisitionHttpTransport(
        sec_user_agent_contact=_SEC_CONTACT,
        opener=opener,
    )

    with pytest.raises(HttpTransportBoundaryError):
        transport.send(wire)

    assert opener.calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("request_identity", 1),
        ("provider", []),
        ("method", 1),
        ("endpoint_path", 1),
        ("body_sha256", 1),
    ),
)
def test_wrong_typed_wire_scalars_are_rejected_before_io(
    field: str, value: object
) -> None:
    opener = _FakeOpener(())
    transport = TestOnlyStdlibAcquisitionHttpTransport(opener=opener)
    valid = _wire(
        "OPENFIGI",
        "/v3/mapping",
        method="POST",
        body=b"[]",
        headers=(
            ("accept", "application/json"),
            ("content-type", "application/json"),
        ),
    )
    wire = replace(valid, **{field: value})

    with pytest.raises(
        HttpTransportBoundaryError, match="^HTTP_WIRE_SCALAR_TYPE_INVALID$"
    ):
        transport.send(wire)

    assert opener.calls == []


def test_urllib_timeout_limitation_fails_closed() -> None:
    with pytest.raises(ValueError, match="^URLLIB_UNIFIED_SOCKET_TIMEOUT_REQUIRED$"):
        TestOnlyStdlibAcquisitionHttpTransport(
            connect_timeout_seconds=10,
            read_timeout_seconds=20,
            opener=_FakeOpener(()),
        )
