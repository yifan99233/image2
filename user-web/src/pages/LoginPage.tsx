import { FormEvent, useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { Eye, EyeOff, Lock, Mail } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { AuthPageLayout } from "@/pages/AuthPageLayout";
import { useAuthStore } from "@/stores/authStore";
import { authPathWithInviteContext } from "@/utils/authInviteContext";
import { SiteBrandIcon } from "@/components/branding/SiteBrandIcon";

type LocationState = {
  from?: { pathname?: string };
  sessionExpired?: boolean;
  inviteCode?: string;
  referralToken?: string;
};

const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export const LoginPage = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const login = useAuthStore((state) => state.login);
  const status = useAuthStore((state) => state.status);
  const loginError = useAuthStore((state) => state.loginError);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [isPasswordVisible, setIsPasswordVisible] = useState(false);
  const locationState = location.state as LocationState | null;
  const redirectTo = locationState?.from?.pathname ?? "/create/edit";
  const isSubmitting = status === "checking";

  useEffect(() => {
    if (status === "authenticated") {
      navigate(redirectTo, { replace: true });
    }
  }, [navigate, redirectTo, status]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError(null);

    const account = username.trim().toLowerCase();
    if (!account || !password) {
      setFormError("请输入邮箱账号和密码");
      return;
    }

    if (!emailPattern.test(account)) {
      setFormError("请输入正确的邮箱账号");
      return;
    }

    try {
      await login(account, password);
      navigate(redirectTo, { replace: true });
    } catch {
      // Store keeps the user-facing error message.
    }
  };

  return (
    <AuthPageLayout>
      <section className="auth-card" aria-labelledby="login-title">
        <div className="auth-card__hero">
          <span className="auth-card__logo">
            <SiteBrandIcon />
          </span>
          <p className="eyebrow">欢迎回来</p>
          <h2 id="login-title">继续你的创作</h2>
          <p className="auth-card__hint">登录后继续使用你的 AI 工作流。</p>
        </div>

        {locationState?.sessionExpired ? <div className="notice notice--warning">登录已过期，请重新登录。</div> : null}

        <form className="form" onSubmit={handleSubmit}>
          <label>
            <span>
              <Mail size={15} />
              邮箱账号
            </span>
            <input
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="请输入邮箱账号"
            />
          </label>
          <label>
            <span>
              <Lock size={15} />
              密码
            </span>
            <div className="password-field">
              <input
                autoComplete="current-password"
                type={isPasswordVisible ? "text" : "password"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="请输入密码"
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

          <Button fullWidth isLoading={isSubmitting} type="submit">
            立即登录
          </Button>
        </form>

        <p className="auth-switch">
          还没有账号？ <Link to={authPathWithInviteContext("/register", searchParams)} state={locationState}>立即注册</Link>
        </p>
      </section>
    </AuthPageLayout>
  );
};
