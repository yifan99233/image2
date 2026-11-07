import { FormEvent, useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Building2, Eye, EyeOff, LoaderCircle, Lock, Mail, User } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { AuthPageLayout } from "@/pages/AuthPageLayout";
import { useAuthStore } from "@/stores/authStore";
import { authService } from "@/services/auth";
import type { TeamInvitePreview } from "@/types/api";
import { authPathWithInviteContext, searchWithoutInviteCode } from "@/utils/authInviteContext";
import { SiteBrandIcon } from "@/components/branding/SiteBrandIcon";
import { loadSiteConfig, readCachedSiteConfig } from "@/services/siteConfigStore";

const strongPasswordPattern = /^(?=.*[A-Za-z])(?=.*\d).{8,}$/;
const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type RegisterLocationState = {
  inviteCode?: string;
  referralToken?: string;
};

export const RegisterPage = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { referralToken: referralTokenParam } = useParams<{ referralToken?: string }>();
  const [searchParams] = useSearchParams();
  const locationState = location.state as RegisterLocationState | null;
  const [siteConfig, setSiteConfig] = useState(readCachedSiteConfig);
  const register = useAuthStore((state) => state.register);
  const status = useAuthStore((state) => state.status);
  const loginError = useAuthStore((state) => state.loginError);
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [isPasswordVisible, setIsPasswordVisible] = useState(false);
  const isSubmitting = status === "checking";
  const [inviteCode] = useState(() => searchParams.get("invite_code")?.trim() || locationState?.inviteCode?.trim() || "");
  const [referralToken] = useState(() => referralTokenParam?.trim() || locationState?.referralToken?.trim() || "");
  const teamInviteToken = searchParams.get("team_invite_token")?.trim() ?? "";
  const [teamInvitePreview, setTeamInvitePreview] = useState<TeamInvitePreview | null>(null);
  const [teamInviteError, setTeamInviteError] = useState<string | null>(null);
  const [isCheckingTeamInvite, setIsCheckingTeamInvite] = useState(Boolean(teamInviteToken));

  useEffect(() => {
    if (!searchParams.has("invite_code") && !referralTokenParam) return;

    const nextSearch = searchWithoutInviteCode(searchParams);
    navigate(
      {
        pathname: "/register",
        search: nextSearch ? `?${nextSearch}` : "",
        hash: location.hash,
      },
      {
        replace: true,
        state: {
          ...locationState,
          inviteCode,
          referralToken,
        },
      },
    );
  }, [inviteCode, location.hash, locationState, navigate, referralToken, referralTokenParam, searchParams]);

  useEffect(() => {
    let ignore = false;
    loadSiteConfig().then((config) => {
      if (!ignore) setSiteConfig(config);
    });
    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    setTeamInvitePreview(null);
    setTeamInviteError(null);
    if (!teamInviteToken) {
      setIsCheckingTeamInvite(false);
      return;
    }
    if (inviteCode || referralToken) {
      setTeamInviteError("团队加入链接不能与奖励邀请码同时使用");
      setIsCheckingTeamInvite(false);
      return;
    }
    let ignore = false;
    setIsCheckingTeamInvite(true);
    authService.getTeamInvitePreview(teamInviteToken)
      .then((preview) => {
        if (!ignore) setTeamInvitePreview(preview);
      })
      .catch((error) => {
        if (!ignore) setTeamInviteError(error instanceof Error ? error.message : "团队邀请链接无效");
      })
      .finally(() => {
        if (!ignore) setIsCheckingTeamInvite(false);
      });
    return () => { ignore = true; };
  }, [inviteCode, referralToken, teamInviteToken]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError(null);

    const normalizedEmail = email.trim().toLowerCase();
    if (!username.trim() || !normalizedEmail || !password) {
      setFormError("请完整填写注册信息");
      return;
    }

    if (!emailPattern.test(normalizedEmail)) {
      setFormError("请输入正确的邮箱账号");
      return;
    }

    if (!strongPasswordPattern.test(password)) {
      setFormError("密码至少 8 位，并同时包含字母和数字");
      return;
    }

    if (teamInviteToken && (isCheckingTeamInvite || !teamInvitePreview)) {
      setFormError(teamInviteError || "正在校验团队邀请链接，请稍后再试");
      return;
    }

    try {
      await register({
        username: username.trim(),
        email: normalizedEmail,
        password,
        invite_code: inviteCode || undefined,
        referral_token: referralToken || undefined,
        team_invite_token: teamInviteToken || undefined,
      });
      navigate("/create/edit", { replace: true });
    } catch {
      // Store keeps the user-facing error message.
    }
  };

  return (
    <AuthPageLayout>
      <section className="auth-card" aria-labelledby="register-title">
        <div className="auth-card__hero">
          <span className="auth-card__logo">
            <SiteBrandIcon />
          </span>
          <p className="eyebrow">开启旅程</p>
          <h2 id="register-title">注册{siteConfig.site_name}</h2>
          <p className="auth-card__hint">创建账号后即可进入模型创作工作台。</p>
          {inviteCode || referralToken ? <p className="auth-card__hint">邀请信息已识别，注册后会自动绑定邀请关系。</p> : null}
        </div>

        {isCheckingTeamInvite ? <div className="team-invite-context is-loading"><LoaderCircle className="spin" size={18} /><div><strong>正在确认团队邀请</strong><p>请稍候，确认后即可注册加入。</p></div></div> : null}
        {teamInvitePreview ? <div className="team-invite-context"><Building2 size={19} /><div><strong>加入团队：{teamInvitePreview.team_name}</strong><p>注册成功后将直接成为团队成员，此链接不参与邀请奖励。</p></div></div> : null}
        {teamInviteError ? <div className="notice notice--error">{teamInviteError}</div> : null}

        <form className="form" onSubmit={handleSubmit}>
          <label>
            <span>
              <User size={15} />
              用户名
            </span>
            <input
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="例如：胖虎"
            />
          </label>
          <label>
            <span>
              <Mail size={15} />
              邮箱
            </span>
            <input
              autoComplete="email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="邮箱将作为登录账号"
            />
          </label>
          <label>
            <span>
              <Lock size={15} />
              密码
            </span>
            <div className="password-field">
              <input
                autoComplete="new-password"
                type={isPasswordVisible ? "text" : "password"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="至少 8 位，包含字母和数字"
              />
              <button
                type="button"
                aria-label={isPasswordVisible ? "隐藏密码" : "查看密码"}
                aria-pressed={isPasswordVisible}
                title={isPasswordVisible ? "隐藏密码" : "查看密码"}
                onClick={() => setIsPasswordVisible((visible) => !visible)}
              >
                {isPasswordVisible ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
          </label>

          {formError || loginError ? <div className="notice notice--error">{formError ?? loginError}</div> : null}

          <Button fullWidth isLoading={isSubmitting} disabled={Boolean(teamInviteToken) && (isCheckingTeamInvite || !teamInvitePreview)} type="submit">
            {teamInvitePreview ? "注册并加入团队" : "注册并进入"}
          </Button>
        </form>

        <p className="auth-switch">
          已有账号？ <Link to={authPathWithInviteContext("/login", searchParams)} state={{ ...locationState, inviteCode, referralToken }}>返回登录</Link>
        </p>
      </section>
    </AuthPageLayout>
  );
};
