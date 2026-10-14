import { useEffect, useRef, useState } from "react";
import { LogIn } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/Button";
import { AuthPageLayout } from "@/pages/AuthPageLayout";
import { useAuthStore } from "@/stores/authStore";


export const AdminImpersonationPage = () => {
  const navigate = useNavigate();
  const impersonate = useAuthStore((state) => state.impersonate);
  const [error, setError] = useState("");
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    const hashParams = new URLSearchParams(window.location.hash.slice(1));
    const code = hashParams.get("code")?.trim() ?? "";
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
    if (!code) {
      setError("代登录链接无效，请返回管理后台重新发起");
      return;
    }

    void impersonate(code)
      .then(() => navigate("/dashboard", { replace: true }))
      .catch((impersonationError: unknown) => {
        setError(impersonationError instanceof Error ? impersonationError.message : "代登录失败，请重新发起");
      });
  }, [impersonate, navigate]);

  return (
    <AuthPageLayout>
      <section className="auth-card" aria-labelledby="admin-impersonation-title">
        <div className="auth-card__hero">
          <span className="auth-card__logo">
            <LogIn size={26} aria-hidden />
          </span>
          <p className="eyebrow">管理员代登录</p>
          <h2 id="admin-impersonation-title">{error ? "无法完成代登录" : "正在进入用户工作台"}</h2>
          <p className="auth-card__hint">
            {error || "正在验证一次性登录链接，请稍候。代登录会话将在 1 小时后失效。"}
          </p>
        </div>

        {error ? <div className="notice notice--error">{error}</div> : <div className="notice">正在安全验证登录身份…</div>}
        {error ? (
          <Button fullWidth type="button" onClick={() => navigate("/login", { replace: true })}>
            返回普通登录
          </Button>
        ) : (
          <Button fullWidth type="button" isLoading disabled>
            正在代登录
          </Button>
        )}
      </section>
    </AuthPageLayout>
  );
};
