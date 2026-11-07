import pytest

from app.core.exceptions import BusinessError
from app.services.team_invites import create_team_invite_token, decode_team_invite_token


def test_team_invite_token_round_trip_keeps_team_scope():
    token, expires_at = create_team_invite_token(team_id=31, site_id=7, issuer_user_id=52)

    claims = decode_team_invite_token(token)

    assert claims == {
        "team_id": 31,
        "site_id": 7,
        "issuer_user_id": 52,
        "expires_at": expires_at.replace(microsecond=0),
    }


def test_team_invite_token_rejects_tampering():
    token, _ = create_team_invite_token(team_id=31, site_id=7, issuer_user_id=52)
    header, payload, signature = token.split(".")
    replacement = "a" if signature[0] != "a" else "b"
    tampered_token = f"{header}.{payload}.{replacement}{signature[1:]}"

    with pytest.raises(BusinessError) as exc_info:
        decode_team_invite_token(tampered_token)

    assert exc_info.value.code == 40078
