from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.exceptions import BusinessError
from app.core.responses import StandardResponse, ok
from app.db.session import get_db
from app.models.lead_module import LeadTrialApplication, UserLeadModule
from app.models.user import User

router = APIRouter(prefix="/leads", tags=["leads"])


class LeadModuleStatus(BaseModel):
    is_enabled: bool
    enterprise_id: str | None = None
    opened_at: str | None = None
    credentials_revealed_at: str | None = None
    can_reveal_credentials: bool = False


class LeadModuleCredentials(BaseModel):
    enterprise_account: str
    enterprise_password: str
    credentials_revealed_at: str


class LeadTrialApplicationRequest(BaseModel):
    business_scope: str = Field(default="", max_length=3000)
    keywords: str = Field(default="", max_length=2000)
    competitor_accounts: str = Field(default="", max_length=2000)
    contact_info: str = Field(min_length=1, max_length=255)


class LeadTrialApplicationOut(BaseModel):
    id: int
    business_scope: str
    keywords: str
    competitor_accounts: str
    contact_info: str
    status: str
    admin_remark: str = ""
    created_at: str | None = None
    updated_at: str | None = None


def trial_application_out(application: LeadTrialApplication) -> LeadTrialApplicationOut:
    return LeadTrialApplicationOut(
        id=application.id,
        business_scope=application.business_scope,
        keywords=application.keywords,
        competitor_accounts=application.competitor_accounts,
        contact_info=application.contact_info,
        status=application.status,
        admin_remark=application.admin_remark or "",
        created_at=application.created_at.isoformat() if application.created_at else None,
        updated_at=application.updated_at.isoformat() if application.updated_at else None,
    )


@router.get("/module", response_model=StandardResponse[LeadModuleStatus])
async def lead_module_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[LeadModuleStatus]:
    module = await db.scalar(select(UserLeadModule).where(UserLeadModule.user_id == current_user.id))
    if module is None or not module.is_enabled:
        return ok(LeadModuleStatus(is_enabled=False))
    return ok(
        LeadModuleStatus(
            is_enabled=True,
            enterprise_id=module.enterprise_id,
            opened_at=module.created_at.isoformat() if module.created_at else None,
            credentials_revealed_at=module.credentials_revealed_at.isoformat() if module.credentials_revealed_at else None,
            can_reveal_credentials=module.credentials_revealed_at is None,
        )
    )


@router.get("/trial-applications/latest", response_model=StandardResponse[LeadTrialApplicationOut | None])
async def latest_trial_application(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[LeadTrialApplicationOut | None]:
    application = await db.scalar(
        select(LeadTrialApplication)
        .where(LeadTrialApplication.user_id == current_user.id, LeadTrialApplication.site_id == current_user.site_id)
        .order_by(desc(LeadTrialApplication.created_at), desc(LeadTrialApplication.id))
        .limit(1)
    )
    return ok(trial_application_out(application) if application else None)


@router.post("/trial-applications", response_model=StandardResponse[LeadTrialApplicationOut])
async def create_trial_application(
    payload: LeadTrialApplicationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[LeadTrialApplicationOut]:
    business_scope = payload.business_scope.strip()
    keywords = payload.keywords.strip()
    competitor_accounts = payload.competitor_accounts.strip()
    contact_info = payload.contact_info.strip()
    if not contact_info:
        raise BusinessError("请填写联系方式", code=40001)

    application = LeadTrialApplication(
        site_id=current_user.site_id,
        user_id=current_user.id,
        business_scope=business_scope,
        keywords=keywords,
        competitor_accounts=competitor_accounts,
        contact_info=contact_info,
        status="pending",
    )
    db.add(application)
    await db.commit()
    await db.refresh(application)
    return ok(trial_application_out(application), message="申请已提交")


@router.post("/module/credentials", response_model=StandardResponse[LeadModuleCredentials])
async def reveal_lead_module_credentials(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[LeadModuleCredentials]:
    module = await db.scalar(select(UserLeadModule).where(UserLeadModule.user_id == current_user.id))
    if module is None or not module.is_enabled:
        raise BusinessError("客资模块未开通", code=42001, status_code=403)
    if module.credentials_revealed_at is not None:
        raise BusinessError("企业账号和密码已展示过，如需重置请联系管理员", code=42002, status_code=409)

    revealed_at = datetime.now(UTC)
    module.credentials_revealed_at = revealed_at
    await db.commit()
    return ok(
        LeadModuleCredentials(
            enterprise_account=module.enterprise_account,
            enterprise_password=module.enterprise_password_secret,
            credentials_revealed_at=revealed_at.isoformat(),
        )
    )
