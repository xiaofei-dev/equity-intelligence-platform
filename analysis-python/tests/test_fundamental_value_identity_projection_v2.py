from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from equity_analysis.fundamental_value.identity_projection_v2 import (
    CONTRACT_VERSION,
    IdentityProjectionV2Stop,
    load_accepted_identity_projection_v2,
    projection_v2_to_wire,
    validate_identity_projection_v2,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
STAGE8C_STORAGE = (
    REPOSITORY_ROOT
    / "storage/fundamental-value-forward-enrollment-v1/stage8c"
)


@pytest.fixture(scope="module")
def accepted_projection():
    marker = STAGE8C_STORAGE / ".fv-stage8c-private-storage.json"
    if not marker.is_file():
        pytest.skip("accepted private Stage 8C storage is not available")
    return load_accepted_identity_projection_v2(
        repository_root=REPOSITORY_ROOT,
        storage_root=STAGE8C_STORAGE,
    )


def test_accepted_projection_replays_all_three_authorities(accepted_projection) -> None:
    assert accepted_projection.contract_version == CONTRACT_VERSION
    assert accepted_projection.content_hash == (
        "sha256:96887c70c369f412a2bfbb480ebe176db841cacb0c9a6f9c2618ee36c2bcf545"
    )
    assert tuple(item.ticker for item in accepted_projection.members) == (
        "GOOG",
        "FOX",
        "MSFT",
    )
    assert tuple(item.adoption_state for item in accepted_projection.members) == (
        "NEW_ID_CANDIDATE",
        "NEW_ID_CANDIDATE",
        "ADOPT_EXISTING_PUBLIC_ID_V22_GRAPH_REQUIRED",
    )
    assert accepted_projection.members[2].security_id == (
        "08618c07-7979-49cb-abad-ce43305952c6"
    )
    assert accepted_projection.v22_write_authorized is True
    assert accepted_projection.v24_enrollment_authorized is False
    assert accepted_projection.investment_assessment_authorized is False
    assert accepted_projection.evidence_label_upgrade_authorized is False


def test_projection_wire_is_canonical_and_value_preserving(accepted_projection) -> None:
    wire = projection_v2_to_wire(accepted_projection)
    assert wire["contentHash"] == accepted_projection.content_hash
    assert wire["members"][0]["ticker"] == "GOOG"
    assert wire["members"][1]["ticker"] == "FOX"
    assert wire["members"][2]["ticker"] == "MSFT"
    assert wire["modelEvidenceLabel"] == "NOT_VALIDATED"


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("v22_write_authorized", False, "PROJECTION_V2_ROOT_BINDING_DRIFT"),
        ("v24_enrollment_authorized", True, "PROJECTION_V2_ROOT_BINDING_DRIFT"),
        (
            "evidence_label_upgrade_authorized",
            True,
            "PROJECTION_V2_ROOT_BINDING_DRIFT",
        ),
    ],
)
def test_projection_authority_cannot_expand(
    accepted_projection, field: str, value: bool, code: str
) -> None:
    with pytest.raises(IdentityProjectionV2Stop, match=code):
        validate_identity_projection_v2(replace(accepted_projection, **{field: value}))


def test_projection_rejects_identity_or_provider_tamper(accepted_projection) -> None:
    first = accepted_projection.members[0]
    with pytest.raises(
        IdentityProjectionV2Stop, match="PROJECTION_V2_MEMBER_BINDING_DRIFT"
    ):
        validate_identity_projection_v2(
            replace(
                accepted_projection,
                members=(replace(first, mic="XNYS"), *accepted_projection.members[1:]),
            )
        )
    with pytest.raises(
        IdentityProjectionV2Stop, match="PROJECTION_V2_MEMBER_BINDING_DRIFT"
    ):
        validate_identity_projection_v2(
            replace(
                accepted_projection,
                members=(
                    replace(first, openfigi_provider_identity_hash="0" * 64),
                    *accepted_projection.members[1:],
                ),
            )
        )


def test_projection_requires_frozen_tuple(accepted_projection) -> None:
    with pytest.raises(IdentityProjectionV2Stop, match="PROJECTION_V2_TYPE_INVALID"):
        validate_identity_projection_v2(
            replace(accepted_projection, members=list(accepted_projection.members))  # type: ignore[arg-type]
        )
