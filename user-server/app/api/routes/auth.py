import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.exceptions import BusinessError
from app.core.responses import StandardResponse, ok
from app.db.session import get_db
from app.models.credit import UserCreditAccount
from app.models.user import User
from app.models.user_impersonation_grant import UserImpersonationGrant
from app.schemas.auth import (
    AuthUser,
    ImpersonationExchangeRequest,
    LoginRequest,
    PasswordChangeRequest,
    ProfileUpdateRequest,
    PublicKeyResponse,
    RegisterRequest,
    TokenResponse,
)
from app.services.rate_limit import login_rate_limit_key
from app.services.security import (
    create_access_token,
    create_impersonation_access_token,
    get_public_key_pem,
    hash_password,
    resolve_submitted_password,
    verify_password,
)
from app.services.agent_provisioning import sync_agent_account
from app.services.reward_invites import decode_reward_invite_token
from app.services.site_scope import current_site_id
from app.services.team_invites import get_team_invite_preview, join_team_from_invite

router = APIRouter(prefix="/auth", tags=["auth"])


def parse_invite_code(invite_code: str | None) -> int | None:
    normalized = (invite_code or "").strip().upper()
    if not normalized:
        return None
    if not normalized.startswith("U") or not normalized[1:].isdigit():
        raise BusinessError("邀请码无效", code=40002)
    return int(normalized[1:])


def to_auth_user(user: User) -> AuthUser:
    return AuthUser(
        id=user.id,
        username=user.username,
        email=user.email,
        nickname=user.nickname,
        avatar_url=user.avatar_url,
        is_active=user.is_active,
        invited_by_user_id=user.invited_by_user_id,
        created_at=user.created_at.isoformat() if user.created_at else None,
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
    )


@router.get("/public-key", response_model=StandardResponse[PublicKeyResponse])
async def public_key() -> StandardResponse[PublicKeyResponse]:
    return ok(PublicKeyResponse(public_key=get_public_key_pem()))


@router.get("/team-invite", response_model=StandardResponse[dict])
async def team_invite_preview(
    request: Request,
    token: str = Query(min_length=1, max_length=2048),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    site_id = await current_site_id(db, request)
    return ok(await get_team_invite_preview(db, token=token, current_site_id=site_id))


@router.post("/register", response_model=StandardResponse[TokenResponse])
async def register(data: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)) -> StandardResponse[TokenResponse]:
    password = resolve_submitted_password(data.password)
    email = str(data.email).strip().lower()
    site_id = await current_site_id(db, request)
    existing = await db.scalar(select(User.id).where(User.email == email))
    if existing is not None:
        raise BusinessError("邮箱已存在", code=40001)
    team_invite_token = (data.team_invite_token or "").strip()
    referral_token = (data.referral_token or "").strip()
    if team_invite_token and (data.invite_code or referral_token):
        raise BusinessError("团队加入链接不能与奖励邀请码同时使用", code=40008)
    if data.invite_code and referral_token:
        raise BusinessError("邀请信息无效", code=40002)
    invited_by_user_id = (
        decode_reward_invite_token(referral_token, current_site_id=site_id)
        if referral_token
        else parse_invite_code(data.invite_code)
    )
    if invited_by_user_id is not None:
        inviter_id = await db.scalar(
            select(User.id).where(
                User.id == invited_by_user_id,
                User.site_id == site_id,
                User.is_active.is_(True),
                User.deleted_at.is_(None),
            )
        )
        if inviter_id is None:
            raise BusinessError("邀请码无效", code=40002)

    user = User(
        username=data.username,
        site_id=site_id,
        email=email,
        password_hash=hash_password(password),
        nickname=data.nickname,
        invited_by_user_id=invited_by_user_id,
        is_active=True,
    )
    db.add(user)
    try:
        await db.flush()
        if team_invite_token:
            await join_team_from_invite(db, invitee=user, token=team_invite_token)
        await sync_agent_account(db, user, password=password)
        db.add(UserCreditAccount(user_id=user.id))
        await db.commit()
    except BusinessError:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        raise BusinessError("邮箱已存在", code=40001) from exc
    await db.refresh(user)
    token = create_access_token(user.id, user.username)
    return ok(TokenResponse(access_token=token, user=to_auth_user(user)), "注册成功")


@router.post("/login", response_model=StandardResponse[TokenResponse])
async def login(
    data: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[TokenResponse]:
    account = data.username.strip().lower()
    identifier = f"{request.client.host if request.client else 'unknown'}:{account}"
    if not await login_rate_limit_key(identifier):
        raise BusinessError("登录尝试过于频繁，请稍后再试", code=42901, status_code=429)

    site_id = await current_site_id(db, request)
    user = await db.scalar(select(User).where(User.site_id == site_id, or_(User.email == account, User.username == data.username.strip()), User.deleted_at.is_(None)))
    if user is None:
        raise BusinessError("用户名或密码错误", code=40003, status_code=401)
    if not user.is_active:
        raise BusinessError("账户已被禁用", code=40103, status_code=401)

    password = resolve_submitted_password(data.password)
    if not verify_password(password, user.password_hash):
        raise BusinessError("用户名或密码错误", code=40003, status_code=401)

    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)
    token = create_access_token(user.id, user.username)
    return ok(TokenResponse(access_token=token, user=to_auth_user(user)), "登录成功")


@router.post("/admin-impersonation/exchange", response_model=StandardResponse[TokenResponse])
async def exchange_admin_impersonation(
    data: ImpersonationExchangeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[TokenResponse]:
    now = datetime.now(timezone.utc)
    token_hash = hashlib.sha256(data.code.encode("utf-8")).hexdigest()
    result = await db.execute(
        update(UserImpersonationGrant)
        .where(
            UserImpersonationGrant.token_hash == token_hash,
            UserImpersonationGrant.consumed_at.is_(None),
            UserImpersonationGrant.expires_at > now,
        )
        .values(consumed_at=now)
        .returning(
            UserImpersonationGrant.user_id,
            UserImpersonationGrant.site_id,
            UserImpersonationGrant.admin_id,
            UserImpersonationGrant.admin_username,
        )
    )
    grant = result.one_or_none()
    if grant is None:
        raise BusinessError("代登录链接无效、已使用或已过期", code=40020, status_code=400)

    request_site_id = await current_site_id(db, request)
    if int(grant.site_id) != request_site_id:
        await db.commit()
        raise BusinessError("代登录链接不属于当前站点", code=40320, status_code=403)

    user = await db.scalar(
        select(User).where(
            User.id == grant.user_id,
            User.site_id == request_site_id,
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
    )
    if user is None:
        await db.commit()
        raise BusinessError("用户不存在或账户已被禁用", code=40103, status_code=401)

    await db.commit()
    token = create_impersonation_access_token(
        user.id,
        user.username,
        admin_id=int(grant.admin_id),
        admin_username=str(grant.admin_username),
        expires_delta=timedelta(hours=1),
    )
    return ok(TokenResponse(access_token=token, user=to_auth_user(user)), "代登录成功")


@router.get("/me", response_model=StandardResponse[AuthUser])
async def me(current_user: User = Depends(get_current_user)) -> StandardResponse[AuthUser]:
    return ok(to_auth_user(current_user))


@router.patch("/profile", response_model=StandardResponse[AuthUser])
async def update_profile(
    data: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[AuthUser]:
    email = str(data.email).strip().lower()
    nickname = data.nickname.strip() if data.nickname else None
    avatar_url = data.avatar_url.strip() if data.avatar_url else None

    existing = await db.scalar(
        select(User.id).where(
            User.email == email,
            User.id != current_user.id,
        )
    )
    if existing is not None:
        raise BusinessError("邮箱已被其他账户使用", code=40004)

    current_user.email = email
    current_user.nickname = nickname or None
    current_user.avatar_url = avatar_url or None
    await db.commit()
    await db.refresh(current_user)
    return ok(to_auth_user(current_user), "资料已更新")


@router.post("/password", response_model=StandardResponse[None])
async def change_password(
    data: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[None]:
    current_password = resolve_submitted_password(data.current_password)
    new_password = resolve_submitted_password(data.new_password)
    if len(new_password) < 8:
        raise BusinessError("新密码至少需要 8 位", code=40005)
    if not verify_password(current_password, current_user.password_hash):
        raise BusinessError("当前密码不正确", code=40006, status_code=400)

    current_user.password_hash = hash_password(new_password)
    await db.commit()
    return ok(None, "密码已更新")
