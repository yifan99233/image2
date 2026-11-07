import { type FormEvent, useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { BarChart3, CircleAlert, Check, LoaderCircle, LogOut, ScrollText, ShieldCheck, UsersRound, X } from "lucide-react";
import { TeamOverviewPage } from "./pages/TeamOverviewPage";
import { TeamUsagePage } from "./pages/TeamUsagePage";
import { TeamUsageRecordsPage } from "./pages/TeamUsageRecordsPage";
import { teamApi, type TeamMember, type TeamSettings } from "./services/team";
import { TeamApiError, teamConsolePath, teamSession } from "./services/api";

type ConsolePage = "overview" | "usage" | "records";

function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setError(""); setIsSubmitting(true); try { const session = await teamApi.login(username.trim(), password); teamSession.set(session.access_token); if (window.location.pathname === "/login" || window.location.pathname === "/login/") { window.location.assign(teamConsolePath); return; } } catch (err) { setError(err instanceof Error ? err.message : "登录失败"); } finally { setIsSubmitting(false); } }
  return <main className="login-page"><section className="login-card"><div className="login-mark"><UsersRound size={24} /></div><p className="eyebrow">IMAGE2 TEAM</p><h1>团队管理中心</h1><p>团队成员可查看本人额度，管理员可管理团队成员与使用上限。</p><form onSubmit={submit}><label>账号<input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required /></label><label>密码<input value={password} onChange={(event) => setPassword(event.target.value)} type="password" autoComplete="current-password" required /></label>{error ? <p className="form-error"><CircleAlert size={15} />{error}</p> : null}<button className="button button-primary" disabled={isSubmitting}>{isSubmitting ? <LoaderCircle className="spin" size={16} /> : null}登录团队管理中心</button></form></section></main>;
}

function TeamConsole({ onLogout }: { onLogout: () => void }) {
  const [settings, setSettings] = useState<TeamSettings | null>(null);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [permissions, setPermissions] = useState<string[]>([]);
  const [page, setPage] = useState<ConsolePage>("overview");
  const [isLoading, setIsLoading] = useState(true);
  const [accessDenied, setAccessDenied] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const reload = useCallback(async () => {
    setIsLoading(true); setError("");
    try {
      const session = await teamApi.getSession();
      const canViewMembers = session.permissions.includes("members:view");
      const nextMembers = canViewMembers ? await teamApi.getMembers() : [];
      setSettings(session.team); setPermissions(session.permissions); setMembers(nextMembers);
      if (!canViewMembers) setPage("usage");
    } catch (err) {
      setAccessDenied(err instanceof TeamApiError && err.status === 403);
      setError(err instanceof Error ? err.message : "团队数据加载失败");
    } finally { setIsLoading(false); }
  }, []);

  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => { if (!notice) return; const timer = window.setTimeout(() => setNotice(""), 3000); return () => window.clearTimeout(timer); }, [notice]);
  useEffect(() => {
    if (!settings?.site_icon_url) return;
    document.querySelectorAll<HTMLLinkElement>('link[rel="icon"], link[rel="apple-touch-icon"]').forEach((link) => {
      link.href = settings.site_icon_url;
    });
  }, [settings?.site_icon_url]);

  if (isLoading) return <main className="loading-screen"><LoaderCircle className="spin" size={28} />正在载入团队管理中心</main>;
  if (accessDenied) return <main className="access-denied"><div><div className="login-mark"><ShieldCheck size={24} /></div><p className="eyebrow">团队访问权限</p><h1>当前账号无法进入团队中心</h1><p>{error || "请确认团队权益和成员身份后重试。"}</p><button className="button button-quiet" onClick={onLogout}>退出登录</button></div></main>;
  if (!settings) return <main className="loading-screen"><CircleAlert size={26} />{error || "团队信息不可用"}<button className="button button-quiet" onClick={() => void reload()}>重新加载</button></main>;

  const canViewOverview = permissions.includes("members:view");
  const canViewTeamUsage = permissions.includes("usage:view");
  const content = page === "overview" && canViewOverview
    ? <TeamOverviewPage settings={settings} members={members} permissions={permissions} onMembersChange={setMembers} onSettingsChange={setSettings} onReload={reload} onNotice={setNotice} onError={setError} />
    : page === "records" && canViewTeamUsage
      ? <TeamUsageRecordsPage members={members} onError={setError} />
      : <TeamUsagePage permissions={permissions} siteName={settings?.site_name || ""} onNotice={setNotice} onError={setError} />;
  return <main className="console"><header className="console-header"><a className="brand" href={teamConsolePath}><span>{settings.site_icon_url ? <img src={settings.site_icon_url} alt="" /> : <UsersRound size={20} />}</span><strong>团队管理中心</strong></a><div className="header-context"><span className="scope-badge"><ShieldCheck size={14} />仅限当前企业</span><button className="account-button" type="button" onClick={onLogout}>退出<LogOut size={15} /></button></div></header><div className="console-body"><aside className="console-nav"><p>团队工作台</p>{canViewOverview ? <button className={page === "overview" ? "is-active" : ""} type="button" onClick={() => setPage("overview")}><UsersRound size={17} />概览与成员</button> : null}<button className={page === "usage" ? "is-active" : ""} type="button" onClick={() => setPage("usage")}><BarChart3 size={17} />额度与用量</button>{canViewTeamUsage ? <button className={page === "records" ? "is-active" : ""} type="button" onClick={() => setPage("records")}><ScrollText size={17} />使用记录</button> : null}<footer><ShieldCheck size={17} /><span>{canViewOverview ? "管理范围仅限当前企业团队。" : "你只能查看自己的额度与用量。"}</span></footer></aside><section className="console-content">{error ? <div className="message message-error"><CircleAlert size={16} />{error}<button type="button" onClick={() => setError("")} aria-label="关闭提示"><X size={16} /></button></div> : null}{notice ? <div className="message message-success"><Check size={16} />{notice}</div> : null}{content}</section></div></main>;
}

export function App() {
  const token = useSyncExternalStore(teamSession.subscribe, teamSession.get);
  return token ? <TeamConsole key={token} onLogout={teamSession.clear} /> : <LoginPage />;
}
