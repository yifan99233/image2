from jose import JWTError, jwt

from app.core.config import settings
from app.core.exceptions import BusinessError

REWARD_INVITE_TOKEN_TYPE = "reward_invite"


def create_reward_invite_token(*, inviter_user_id: int, site_id: int) -> str:
    payload = {
        "typ": REWARD_INVITE_TOKEN_TYPE,
        "sub": str(int(inviter_user_id)),
        "site_id": int(site_id),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_reward_invite_token(token: str, *, current_site_id: int) -> int:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("typ") != REWARD_INVITE_TOKEN_TYPE:
            raise ValueError("unexpected token type")
        inviter_user_id = int(payload["sub"])
        site_id = int(payload["site_id"])
        if inviter_user_id <= 0 or site_id <= 0:
            raise ValueError("invalid identifiers")
    except (JWTError, KeyError, TypeError, ValueError) as exc:
        raise BusinessError("邀请链接无效", code=40002) from exc

    if site_id != current_site_id:
        raise BusinessError("邀请链接不适用于当前站点", code=40002)
    return inviter_user_id
