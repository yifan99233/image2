import { LockKeyhole, UserRound } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { getPublicSiteConfig } from "../services/adminApi";
import { useAuth } from "../store/auth";
import { adminBrandName } from "../lib/adminBrand";
import { applySiteIcon, DEFAULT_SITE_ICON_URL } from "../lib/siteBranding";

export function LoginPage() {
  const { isAuthenticated, login } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [siteName, setSiteName] = useState("艺源");
  const [siteIconUrl, setSiteIconUrl] = useState(DEFAULT_SITE_ICON_URL);
  const adminName = adminBrandName(siteName);
  const from = (location.state as { from?: string } | null)?.from ?? "/dashboard";

  useEffect(() => {
    let ignore = false;
    getPublicSiteConfig()
      .then((config) => {
        if (!ignore) {
          setSiteName(config.site_name || "艺源");
          setSiteIconUrl(config.site_icon_url || DEFAULT_SITE_ICON_URL);
          applySiteIcon(config.site_icon_url);
        }
      })
      .catch(() => undefined);
    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    document.title = `登录 - ${adminName}`;
  }, [adminName]);

  if (isAuthenticated) {
    return <Navigate to={from} replace />;
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");

    if (!username.trim() || !password.trim()) {
      setError("请输入管理员账号和密码。");
      return;
    }

    setIsSubmitting(true);
    try {
      await login(username.trim(), password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败，请稍后重试。");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-panel" aria-label="管理员登录">
        <div className="login-copy">
          <div className="brand-mark large">
            <img src={siteIconUrl} alt="" />
          </div>
          <h1>{adminName}</h1>
          <p>管理用户、积分、模型配置和任务处理的独立运营后台。</p>
        </div>

        <form className="login-form" onSubmit={onSubmit}>
          <div>
            <span className="eyebrow">管理员登录</span>
            <h2>进入控制台</h2>
          </div>

          <label className="field">
            <span>账号</span>
            <div className="input-shell">
              <UserRound size={18} />
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                autoComplete="username"
              />
            </div>
          </label>

          <label className="field">
            <span>密码</span>
            <div className="input-shell">
              <LockKeyhole size={18} />
              <input
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                type="password"
                autoComplete="current-password"
              />
            </div>
          </label>

          {error ? <div className="form-error">{error}</div> : null}

          <button className="primary-button" type="submit" disabled={isSubmitting}>
            {isSubmitting ? "登录中..." : "登录"}
          </button>
        </form>
      </section>
    </main>
  );
}
