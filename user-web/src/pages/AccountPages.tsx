import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import {
  BadgeCheck,
  CalendarDays,
  CheckCircle2,
  Coins,
  KeyRound,
  Mail,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { authService } from "@/services/auth";
import { creditService } from "@/services/credits";
import { useAuthStore } from "@/stores/authStore";
import type { CreditBalance } from "@/types/api";

const formatDateTime = (value?: string | null) => {
  if (!value) return "暂无记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
};

const AccountSummary = ({ balance }: { balance: CreditBalance | null }) => {
  const user = useAuthStore((state) => state.user);
  if (!user) return null;

  return (
    <aside className="account-summary">
      <div className="account-avatar account-avatar--large">
        {user.avatar_url ? <img src={user.avatar_url} alt={user.username} /> : <UserRound size={30} />}
      </div>
      <div>
        <h2>{user.username}</h2>
        <p>{user.email}</p>
      </div>
      <div className="account-status-pill">
        <BadgeCheck size={16} />
        {user.is_active ? "账号正常" : "账号停用"}
      </div>
      <dl className="account-meta-list">
        <div>
          <dt><Mail size={15} /> 邮箱</dt>
          <dd>{user.email}</dd>
        </div>
        <div>
          <dt><Coins size={15} /> 当前积分</dt>
          <dd>{balance ? balance.balance.toLocaleString() : "--"}</dd>
        </div>
        <div>
          <dt><CalendarDays size={15} /> 注册时间</dt>
          <dd>{formatDateTime(user.created_at)}</dd>
        </div>
        <div>
          <dt><ShieldCheck size={15} /> 最近登录</dt>
          <dd>{formatDateTime(user.last_login_at)}</dd>
        </div>
      </dl>
    </aside>
  );
};

export const AccountProfilePage = () => {
  const user = useAuthStore((state) => state.user);
  const [balance, setBalance] = useState<CreditBalance | null>(null);

  useEffect(() => {
    let ignore = false;
    creditService.getBalance().then((data) => {
      if (!ignore) setBalance(data);
    }).catch(() => {
      if (!ignore) setBalance(null);
    });
    return () => {
      ignore = true;
    };
  }, []);

  return (
    <main className="page-surface account-page">
      <header className="page-header">
        <div>
          <h1>账号资料</h1>
          <p>账号信息来自当前登录账户，仅用于展示。</p>
        </div>
        <Link className="button button--secondary" to="/credits/ledger">
          <Coins size={17} />
          积分记录
        </Link>
      </header>

      <section className="account-layout">
        <AccountSummary balance={balance} />
        <section className="account-panel">
          <div className="account-panel__header">
            <div>
              <h2>基础信息</h2>
              <p>用户名即昵称，邮箱为登录账号。当前页面不提供资料修改入口。</p>
            </div>
          </div>
          <dl className="account-readonly-grid">
            <div>
              <dt>用户名</dt>
              <dd>{user?.username ?? "--"}</dd>
            </div>
            <div>
              <dt>邮箱账号</dt>
              <dd>{user?.email ?? "--"}</dd>
            </div>
            <div>
              <dt>账号状态</dt>
              <dd>{user?.is_active ? "正常" : "停用"}</dd>
            </div>
            <div>
              <dt>最近登录</dt>
              <dd>{formatDateTime(user?.last_login_at)}</dd>
            </div>
          </dl>
          <div className="account-actions">
            <Link className="button button--primary" to="/account/settings">修改密码</Link>
          </div>
        </section>
      </section>
    </main>
  );
};

export const AccountSettingsPage = () => {
  const user = useAuthStore((state) => state.user);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordMessage, setPasswordMessage] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [isPasswordSubmitting, setIsPasswordSubmitting] = useState(false);

  const securityItems = useMemo(
    () => [
      { label: "登录密码", value: "已启用", icon: KeyRound },
      { label: "账户状态", value: user?.is_active ? "正常" : "停用", icon: ShieldCheck },
      { label: "最近登录", value: formatDateTime(user?.last_login_at), icon: CalendarDays },
    ],
    [user],
  );

  useEffect(() => {
    if (!passwordMessage) return;
    const timerId = window.setTimeout(() => setPasswordMessage(null), 3000);
    return () => window.clearTimeout(timerId);
  }, [passwordMessage]);

  async function submitPassword(event: FormEvent) {
    event.preventDefault();
    setPasswordError(null);
    setPasswordMessage(null);
    if (newPassword.length < 8) {
      setPasswordError("新密码至少需要 8 位");
      return;
    }
    if (newPassword !== confirmPassword) {
      setPasswordError("两次输入的新密码不一致");
      return;
    }
    setIsPasswordSubmitting(true);
    try {
      await authService.changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setPasswordMessage("密码已更新，下次登录请使用新密码");
    } catch (err) {
      setPasswordError(err instanceof Error ? err.message : "密码更新失败");
    } finally {
      setIsPasswordSubmitting(false);
    }
  }

  return (
    <main className="page-surface account-page">
      <header className="page-header">
        <div>
          <h1>账号设置</h1>
          <p>账号资料只读，修改密码需要验证当前密码。</p>
        </div>
      </header>

      <section className="settings-grid settings-grid--account">
        <div className="account-panel">
          <div className="account-panel__header">
            <div>
              <h2>安全状态</h2>
              <p>这些状态来自当前登录账户。</p>
            </div>
          </div>
          <div className="security-list">
            {securityItems.map((item) => {
              const Icon = item.icon;
              return (
                <div className="security-item" key={item.label}>
                  <span><Icon size={17} /></span>
                  <div>
                    <strong>{item.label}</strong>
                    <small>{item.value}</small>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <section className="account-panel">
          <div className="account-panel__header">
            <div>
              <h2>账号资料</h2>
              <p>昵称使用用户名，邮箱为登录账号。</p>
            </div>
          </div>
          <dl className="account-readonly-grid account-readonly-grid--compact">
            <div>
              <dt>用户名</dt>
              <dd>{user?.username ?? "--"}</dd>
            </div>
            <div>
              <dt>邮箱账号</dt>
              <dd>{user?.email ?? "--"}</dd>
            </div>
          </dl>
        </section>

        <form className="account-panel account-panel--wide password-reset-panel" onSubmit={submitPassword}>
          <div className="account-panel__header">
            <div>
              <h2>修改密码</h2>
              <p>新密码至少 8 位，提交后下次登录生效。</p>
            </div>
          </div>
          <div className="password-reset-fields">
            <label>
              <span>当前密码</span>
              <input type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} required autoComplete="current-password" />
            </label>
            <label>
              <span>新密码</span>
              <input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} required minLength={8} autoComplete="new-password" />
            </label>
            <label>
              <span>确认新密码</span>
              <input type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} required minLength={8} autoComplete="new-password" />
            </label>
          </div>
          {passwordMessage ? <div className="notice notice--success"><CheckCircle2 size={16} />{passwordMessage}</div> : null}
          {passwordError ? <div className="notice notice--error">{passwordError}</div> : null}
          <div className="account-actions">
            <Button type="submit" isLoading={isPasswordSubmitting}>更新密码</Button>
          </div>
        </form>
      </section>
    </main>
  );
};
