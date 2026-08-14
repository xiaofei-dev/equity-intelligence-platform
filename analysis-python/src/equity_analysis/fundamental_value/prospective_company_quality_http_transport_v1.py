"""Fail-closed stdlib HTTP transport for the Stage 8C acquisition contract.

Construction performs no I/O. Network access occurs only when ``send`` is
called with an already sealed ``ProviderWireRequest``. The transport owns no
retry policy and deliberately exposes only stable, sanitized failure codes.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import ssl
from email.message import Message
from http.client import HTTPMessage
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import (
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)

from .prospective_company_quality_acquisition_v1 import (
    MAX_RESPONSE_BODY_BYTES,
    PARSER_REGISTRY_CONTENT_HASH,
    ProviderWireRequest,
    TransportResponse,
)

PRODUCTION_TRANSPORT_VERSION = "FV-STAGE8C-STDLIB-HTTP-TRANSPORT-v1.1.0"
TRANSPORT_VERSION = PRODUCTION_TRANSPORT_VERSION
DEFAULT_CONNECT_TIMEOUT_SECONDS = 20.0
DEFAULT_READ_TIMEOUT_SECONDS = 20.0

_ORIGINS = {
    "OPENFIGI": "https://api.openfigi.com",
    "SEC": "https://www.sec.gov",
    "YAHOO_CHART": "https://query1.finance.yahoo.com",
    "EODHD": "https://eodhd.com",
}
_OPENFIGI_PATH = "/v3/mapping"
_SEC_PATH = "/files/company_tickers_exchange.json"
_YAHOO_PATH = re.compile(
    r"/v8/finance/chart/[A-Z0-9][A-Z0-9.-]{0,31}"
    r"\?range=10d&interval=1d&events=div%2Csplits"
    r"&includeAdjustedClose=true\Z"
)
_EODHD_PATH = re.compile(
    r"/api/fundamentals/[A-Z0-9][A-Z0-9.-]{0,31}\.US\?fmt=json\Z"
)
_EODHD_KEY = re.compile(r"[A-Za-z0-9._~-]{1,512}\Z")
_ENVIRONMENT_VARIABLE = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")
_RESPONSE_HEADER_ALLOWLIST = frozenset(
    {
        "content-type",
        "date",
        "ratelimit-limit",
        "ratelimit-remaining",
        "ratelimit-reset",
        "retry-after",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
    }
)
_OPENFIGI_HEADERS = (
    ("accept", "application/json"),
    ("content-type", "application/json"),
)
_GET_HEADERS = (("accept", "application/json"),)


class HttpTransportBoundaryError(RuntimeError):
    """A sanitized transport failure that must become UNKNOWN upstream."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _Openable(Protocol):
    def open(self, request: Request, *, timeout: float): ...


class _NoRedirectHandler(HTTPRedirectHandler):
    """Prevent urllib from converting a redirect into an unsealed request."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _finite_timeout(value: object, *, code: str) -> float:
    if type(value) not in {int, float}:
        raise ValueError(code)
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0 or parsed > 120:
        raise ValueError(code)
    return parsed


def _validate_contact(value: str | None) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or len(value) > 256
        or "@" not in value
        or any(ord(character) < 32 or ord(character) > 126 for character in value)
    ):
        raise ValueError("SEC_USER_AGENT_CONTACT_INVALID")
    return value


def _validate_eodhd_key(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _EODHD_KEY.fullmatch(value):
        raise ValueError("EODHD_API_KEY_INVALID")
    return value


def _read_environment_value(name: str) -> str | None:
    return os.environ.get(name)


def _validate_wire_request(request: ProviderWireRequest) -> None:
    if type(request) is not ProviderWireRequest:
        raise HttpTransportBoundaryError("HTTP_WIRE_REQUEST_TYPE_INVALID")
    if (
        type(request.request_identity) is not str
        or type(request.provider) is not str
        or type(request.method) is not str
        or type(request.endpoint_path) is not str
        or (
            request.body_sha256 is not None
            and type(request.body_sha256) is not str
        )
    ):
        raise HttpTransportBoundaryError("HTTP_WIRE_SCALAR_TYPE_INVALID")
    if (
        not request.request_identity
        or request.request_identity != request.request_identity.strip()
        or any(character in request.request_identity for character in "\r\n")
    ):
        raise HttpTransportBoundaryError("HTTP_REQUEST_IDENTITY_INVALID")
    if request.provider not in _ORIGINS:
        raise HttpTransportBoundaryError("HTTP_PROVIDER_NOT_ALLOWLISTED")
    if (
        type(request.headers) is not tuple
        or any(
            type(item) is not tuple
            or len(item) != 2
            or not all(type(part) is str for part in item)
            or not item[0]
            or not item[1]
            or item[0] != item[0].strip()
            or item[1] != item[1].strip()
            or any(character in item[0] + item[1] for character in "\r\n")
            for item in request.headers
        )
    ):
        raise HttpTransportBoundaryError("HTTP_REQUEST_HEADERS_INVALID")
    if any(name != name.lower() for name, _value in request.headers):
        raise HttpTransportBoundaryError("HTTP_REQUEST_HEADER_CASE_INVALID")
    if len({name for name, _value in request.headers}) != len(request.headers):
        raise HttpTransportBoundaryError("HTTP_REQUEST_HEADER_DUPLICATE")
    if request.provider == "OPENFIGI":
        if (
            request.method != "POST"
            or request.endpoint_path != _OPENFIGI_PATH
            or request.headers != _OPENFIGI_HEADERS
            or type(request.body) is not bytes
            or not request.body
            or request.body_sha256
            != hashlib.sha256(request.body).hexdigest().upper()
        ):
            raise HttpTransportBoundaryError("OPENFIGI_HTTP_REQUEST_INVALID")
        return
    expected_path = {
        "SEC": request.endpoint_path == _SEC_PATH,
        "YAHOO_CHART": bool(_YAHOO_PATH.fullmatch(request.endpoint_path)),
        "EODHD": bool(_EODHD_PATH.fullmatch(request.endpoint_path)),
    }[request.provider]
    if (
        request.method != "GET"
        or not expected_path
        or request.headers != _GET_HEADERS
        or request.body is not None
        or request.body_sha256 is not None
    ):
        raise HttpTransportBoundaryError("GET_HTTP_REQUEST_INVALID")


def _header_items(headers: object) -> tuple[tuple[str, str], ...]:
    if isinstance(headers, Message | HTTPMessage):
        raw = headers.raw_items()
    elif hasattr(headers, "raw_items"):
        raw = headers.raw_items()
    elif hasattr(headers, "items"):
        raw = headers.items()
    else:
        raise HttpTransportBoundaryError("HTTP_RESPONSE_HEADERS_INVALID")
    result: list[tuple[str, str]] = []
    for raw_name, raw_value in raw:
        if not isinstance(raw_name, str) or not isinstance(raw_value, str):
            raise HttpTransportBoundaryError("HTTP_RESPONSE_HEADER_INVALID")
        name = raw_name.lower()
        if name not in _RESPONSE_HEADER_ALLOWLIST:
            continue
        value = raw_value.strip()
        if (
            not value
            or any(character in name + value for character in "\r\n")
            or any(ord(character) < 32 or ord(character) > 126 for character in value)
        ):
            raise HttpTransportBoundaryError("HTTP_RESPONSE_HEADER_INVALID")
        result.append((name, value))
    if len({name for name, _value in result}) != len(result):
        raise HttpTransportBoundaryError("HTTP_RESPONSE_HEADER_DUPLICATE")
    return tuple(sorted(result))


def _response_status(response: object) -> int:
    status = getattr(response, "status", None)
    if status is None and hasattr(response, "getcode"):
        status = response.getcode()
    if type(status) is not int or status < 100 or status > 599:
        raise HttpTransportBoundaryError("HTTP_RESPONSE_STATUS_INVALID")
    return status


def _response_url(response: object) -> str:
    if not hasattr(response, "geturl"):
        raise HttpTransportBoundaryError("HTTP_RESPONSE_URL_MISSING")
    value = response.geturl()
    if not isinstance(value, str) or not value:
        raise HttpTransportBoundaryError("HTTP_RESPONSE_URL_INVALID")
    return value


class _BaseStdlibAcquisitionHttpTransport:
    """Shared sealed request/response mechanics for exact transport types.

    urllib exposes one socket-operation timeout rather than independently
    enforceable connect and read timers. The constructor therefore fails closed
    unless both policy values are equal, then passes that finite value to
    ``OpenerDirector.open``. There are no retries.
    """

    __slots__ = (
        "_eodhd_api_key_environment_variable",
        "_max_response_body_bytes",
        "_sec_user_agent_contact",
        "_test_eodhd_api_key",
        "_timeout_seconds",
    )

    parser_registry_content_hash = PARSER_REGISTRY_CONTENT_HASH
    transport_contract_version = PRODUCTION_TRANSPORT_VERSION
    transport_version = PRODUCTION_TRANSPORT_VERSION
    proxy_policy = "ENVIRONMENT_PROXIES_DISABLED"
    retry_limit = 0

    def __init__(
        self,
        *,
        sec_user_agent_contact: str | None = None,
        eodhd_api_key_environment_variable: str | None = None,
        test_eodhd_api_key: str | None = None,
        connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        read_timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS,
        max_response_body_bytes: int = MAX_RESPONSE_BODY_BYTES,
    ) -> None:
        connect = _finite_timeout(
            connect_timeout_seconds, code="HTTP_CONNECT_TIMEOUT_INVALID"
        )
        read = _finite_timeout(read_timeout_seconds, code="HTTP_READ_TIMEOUT_INVALID")
        if connect != read:
            raise ValueError("URLLIB_UNIFIED_SOCKET_TIMEOUT_REQUIRED")
        if (
            type(max_response_body_bytes) is not int
            or max_response_body_bytes <= 0
            or max_response_body_bytes > MAX_RESPONSE_BODY_BYTES
        ):
            raise ValueError("HTTP_RESPONSE_BODY_CEILING_INVALID")
        self._sec_user_agent_contact = _validate_contact(sec_user_agent_contact)
        if eodhd_api_key_environment_variable is not None and (
            not isinstance(eodhd_api_key_environment_variable, str)
            or not _ENVIRONMENT_VARIABLE.fullmatch(
                eodhd_api_key_environment_variable
            )
        ):
            raise ValueError("EODHD_API_KEY_ENVIRONMENT_VARIABLE_INVALID")
        self._eodhd_api_key_environment_variable = (
            eodhd_api_key_environment_variable
        )
        self._test_eodhd_api_key = _validate_eodhd_key(test_eodhd_api_key)
        self._timeout_seconds = connect
        self._max_response_body_bytes = max_response_body_bytes

    def _open(self, request: Request, *, timeout: float) -> object:
        raise NotImplementedError

    def _resolve_eodhd_api_key(self) -> str:
        if self.test_only:
            value = self._test_eodhd_api_key
        else:
            variable = self._eodhd_api_key_environment_variable
            value = _read_environment_value(variable) if variable is not None else None
        if value is None:
            raise HttpTransportBoundaryError("EODHD_API_KEY_REQUIRED")
        try:
            validated = _validate_eodhd_key(value)
        except ValueError:
            raise HttpTransportBoundaryError("EODHD_API_KEY_INVALID") from None
        if validated is None:
            raise HttpTransportBoundaryError("EODHD_API_KEY_REQUIRED")
        return validated

    @staticmethod
    def _target_url(
        request: ProviderWireRequest, *, eodhd_api_key: str | None
    ) -> str:
        path = request.endpoint_path
        if request.provider == "EODHD":
            if eodhd_api_key is None:
                raise HttpTransportBoundaryError("EODHD_API_KEY_REQUIRED")
            path = f"{path}&api_token={quote(eodhd_api_key, safe='')}"
        return _ORIGINS[request.provider] + path

    def _request_headers(self, request: ProviderWireRequest) -> dict[str, str]:
        result = dict(request.headers)
        if request.provider == "SEC":
            if self._sec_user_agent_contact is None:
                raise HttpTransportBoundaryError("SEC_USER_AGENT_CONTACT_REQUIRED")
            result["user-agent"] = self._sec_user_agent_contact
        return result

    def _consume(
        self,
        response: object,
        *,
        expected_url: str,
        provider: str,
        eodhd_api_key: str | None,
    ) -> TransportResponse:
        status = _response_status(response)
        if 300 <= status < 400:
            raise HttpTransportBoundaryError("HTTP_REDIRECT_BLOCKED")
        if _response_url(response) != expected_url:
            raise HttpTransportBoundaryError("HTTP_RESPONSE_TARGET_DRIFT")
        headers = _header_items(getattr(response, "headers", None))
        if not hasattr(response, "read"):
            raise HttpTransportBoundaryError("HTTP_RESPONSE_BODY_UNREADABLE")
        body = response.read(self._max_response_body_bytes + 1)
        if type(body) is not bytes:
            raise HttpTransportBoundaryError("HTTP_RESPONSE_BODY_INVALID")
        if len(body) > self._max_response_body_bytes:
            raise HttpTransportBoundaryError("HTTP_RESPONSE_BODY_TOO_LARGE")
        if provider == "EODHD" and eodhd_api_key is not None:
            secret = eodhd_api_key.encode("ascii")
            if secret in body or any(
                eodhd_api_key in name or eodhd_api_key in value
                for name, value in headers
            ):
                raise HttpTransportBoundaryError("EODHD_SECRET_REFLECTION_BLOCKED")
        return TransportResponse(status_code=status, headers=headers, body=body)

    @staticmethod
    def _close(response: object) -> None:
        try:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        except Exception:
            raise HttpTransportBoundaryError("HTTP_RESPONSE_CLOSE_FAILED") from None

    def send(self, request: ProviderWireRequest) -> TransportResponse:
        response: object | None = None
        try:
            _validate_wire_request(request)
            eodhd_api_key = (
                self._resolve_eodhd_api_key()
                if request.provider == "EODHD"
                else None
            )
            expected_url = self._target_url(
                request, eodhd_api_key=eodhd_api_key
            )
            headers = self._request_headers(request)
            outgoing = Request(
                expected_url,
                data=request.body,
                headers=headers,
                method=request.method,
            )
            response = self._open(outgoing, timeout=self._timeout_seconds)
            return self._consume(
                response,
                expected_url=expected_url,
                provider=request.provider,
                eodhd_api_key=eodhd_api_key,
            )
        except HTTPError as error:
            response = error
            status = _response_status(error)
            if 400 <= status <= 599:
                try:
                    return self._consume(
                        error,
                        expected_url=expected_url,
                        provider=request.provider,
                        eodhd_api_key=eodhd_api_key,
                    )
                except HttpTransportBoundaryError:
                    raise
                except Exception:
                    raise HttpTransportBoundaryError("HTTP_ERROR_BODY_READ_FAILED") from None
            raise HttpTransportBoundaryError("HTTP_REDIRECT_BLOCKED") from None
        except HttpTransportBoundaryError:
            raise
        except (URLError, TimeoutError, ssl.SSLError, OSError):
            raise HttpTransportBoundaryError("HTTP_TRANSPORT_UNKNOWN") from None
        except Exception:
            raise HttpTransportBoundaryError("HTTP_TRANSPORT_UNKNOWN") from None
        finally:
            if response is not None:
                self._close(response)


class StdlibAcquisitionHttpTransport(_BaseStdlibAcquisitionHttpTransport):
    """Exact production transport; its opener cannot be caller-supplied."""

    __slots__ = ()

    test_only = False
    transport_kind = "PRODUCTION"

    def __init__(
        self,
        *,
        sec_user_agent_contact: str | None = None,
        eodhd_api_key_environment_variable: str | None = "EODHD_API_KEY",
        connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        read_timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS,
        max_response_body_bytes: int = MAX_RESPONSE_BODY_BYTES,
    ) -> None:
        super().__init__(
            sec_user_agent_contact=sec_user_agent_contact,
            eodhd_api_key_environment_variable=(
                eodhd_api_key_environment_variable
            ),
            connect_timeout_seconds=connect_timeout_seconds,
            read_timeout_seconds=read_timeout_seconds,
            max_response_body_bytes=max_response_body_bytes,
        )

    def _open(self, request: Request, *, timeout: float) -> object:
        opener = build_opener(ProxyHandler({}), _NoRedirectHandler())
        return opener.open(request, timeout=timeout)


class TestOnlyStdlibAcquisitionHttpTransport(
    _BaseStdlibAcquisitionHttpTransport
):
    """Exact offline-test transport that permits an explicit fake opener."""

    __slots__ = ("_test_opener",)

    test_only = True
    __test__ = False
    transport_kind = "TEST_ONLY"

    def __init__(
        self,
        *,
        opener: _Openable,
        sec_user_agent_contact: str | None = None,
        eodhd_api_key: str | None = None,
        connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        read_timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS,
        max_response_body_bytes: int = MAX_RESPONSE_BODY_BYTES,
    ) -> None:
        super().__init__(
            sec_user_agent_contact=sec_user_agent_contact,
            test_eodhd_api_key=eodhd_api_key,
            connect_timeout_seconds=connect_timeout_seconds,
            read_timeout_seconds=read_timeout_seconds,
            max_response_body_bytes=max_response_body_bytes,
        )
        self._test_opener = opener

    def _open(self, request: Request, *, timeout: float) -> object:
        return self._test_opener.open(request, timeout=timeout)


__all__ = [
    "DEFAULT_CONNECT_TIMEOUT_SECONDS",
    "DEFAULT_READ_TIMEOUT_SECONDS",
    "HttpTransportBoundaryError",
    "PRODUCTION_TRANSPORT_VERSION",
    "StdlibAcquisitionHttpTransport",
    "TestOnlyStdlibAcquisitionHttpTransport",
    "TRANSPORT_VERSION",
]
