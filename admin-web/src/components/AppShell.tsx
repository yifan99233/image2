import {
  Activity,
  AlertTriangle,
  Banknote,
  Bell,
  CalendarCheck,
  ChevronDown,
  ClipboardList,
  ContactRound,
  Coins,
  CreditCard,
  Gauge,
  Gift,
  Globe2,
  LogOut,
  Menu,
  MessageSquareText,
  Moon,
  Package2,
  PackageOpen,
  Rocket,
  Route,
  PanelTop,
  ReceiptText,
  Settings2,
  ShieldCheck,
  Sparkles,
  Sun,
  UserRound,
  Users,
  X,
} from "lucide-react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { hasPermission, type Permission } from "../lib/permissions";
import { adminBrandName } from "../lib/adminBrand";
import { applySiteIcon, DEFAULT_SITE_ICON_URL, SITE_ICON_UPDATED_EVENT } from "../lib/siteBranding";
import { getSiteContentConfig } from "../services/adminApi";
import { useAuth } from "../store/auth";
import { toggleThemeMode, useThemeMode } from "../store/theme";
import { useEffect, useRef, useState, type ComponentType } from "react";

type NavItem = {
  label: string;
  path: string;
  permission: Permission;
  icon: ComponentType<{ size?: number }>;
};

type NavGroup = {
  label: string;
  items: NavItem[];
};

const navGroups: NavGroup[] = [
  {
    label: "概览",
    items: [
      { label: "控制台", path: "/dashboard", permission: "dashboard:read", icon: Gauge },
    ],
  },
  {
    label: "站点与账号",
    items: [
      { label: "总后台", path: "/site-config", permission: "site_config:write", icon: Globe2 },
      { label: "系统公告", path: "/announcements", permission: "announcements:write", icon: Bell },
      { label: "素材修改", path: "/site-content", permission: "site_content:write", icon: PanelTop },
      { label: "管理员账号", path: "/admin-accounts", permission: "admin_accounts:write", icon: Users },
    ],
  },
  {
    label: "用户运营",
    items: [
      { label: "用户管理", path: "/users", permission: "users:read", icon: UserRound },
      { label: "VIP 客户等级设置", path: "/vip-tiers", permission: "users:read", icon: ShieldCheck },
      { label: "VIP 客户管理", path: "/vip-customers", permission: "users:read", icon: Users },
      { label: "客资申请开通", path: "/lead-applications", permission: "lead_applications:write", icon: ContactRound },
      { label: "用户反馈", path: "/feedbacks", permission: "feedbacks:write", icon: MessageSquareText },
      { label: "素材管理", path: "/materials", permission: "materials:write", icon: PackageOpen },
    ],
  },
  {
    label: "积分与支付",
    items: [
      { label: "积分流水", path: "/credits", permission: "credits:read", icon: Coins },
      { label: "签到配置", path: "/signin-rewards", permission: "credits:read", icon: CalendarCheck },
      { label: "邀请奖励", path: "/invite-reward", permission: "recharge:write", icon: Gift },
      { label: "兑换码", path: "/redemption-codes", permission: "recharge:write", icon: Gift },
      { label: "充值档位", path: "/recharge-plans", permission: "recharge:write", icon: Banknote },
      { label: "支付配置", path: "/payment/zpay", permission: "recharge:write", icon: CreditCard },
      { label: "充值订单", path: "/recharge-orders", permission: "recharge:write", icon: ClipboardList },
    ],
  },
  {
    label: "模型管理",
    items: [
      { label: "模型规范", path: "/image-specs", permission: "models:write", icon: PanelTop },
      { label: "模型管理", path: "/models", permission: "models:write", icon: Package2 },
      { label: "价格配置", path: "/model-prices", permission: "model_prices:write", icon: ReceiptText },
      { label: "任务管理", path: "/tasks", permission: "tasks:write", icon: Activity },
    ],
  },
  {
    label: "系统运维",
    items: [
      { label: "用户体验配置", path: "/user-experience", permission: "ux_config:write", icon: Sparkles },
      { label: "配置", path: "/agent", permission: "agent:write", icon: Route },
      { label: "OpenAgent 更新", path: "/openagent-releases", permission: "openagent_releases:write", icon: Rocket },
      { label: "审计日志", path: "/audit-logs", permission: "audit:read", icon: ClipboardList },
    ],
  },
];

const navItems = navGroups.flatMap((group) => group.items);

const roleLabel = {
  super_admin: "超级管理员",
  operator: "运营管理员",
  finance: "财务管理员",
  model_admin: "模型管理员",
};

export function AppShell() {
  const { user, logout } = useAuth();
  const themeMode = useThemeMode();
  const location = useLocation();
  const [siteName, setSiteName] = useState(user?.site_name || "艺源");
  const [siteIconUrl, setSiteIconUrl] = useState(DEFAULT_SITE_ICON_URL);
  const [requestError, setRequestError] = useState("");
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => {
    try {
      return new Set(JSON.parse(window.localStorage.getItem("admin-nav-collapsed") ?? "[]") as string[]);
    } catch {
      return new Set();
    }
  });
  const dismissTimer = useRef<number | null>(null);
  const visibleNavGroups = navGroups
    .map((group) => ({ ...group, items: group.items.filter((item) => hasPermission(user, item.permission)) }))
    .filter((group) => group.items.length > 0);
  const current = navItems.find((item) => location.pathname.startsWith(item.path));
  const adminName = adminBrandName(siteName);

  useEffect(() => {
    let ignore = false;
    getSiteContentConfig()
      .then((config) => {
        if (!ignore) {
          setSiteName(config.site_name || user?.site_name || "艺源");
          setSiteIconUrl(config.site_icon_url || DEFAULT_SITE_ICON_URL);
          applySiteIcon(config.site_icon_url);
        }
      })
      .catch(() => {
        if (!ignore) setSiteName(user?.site_name || "艺源");
      });
    return () => {
      ignore = true;
    };
  }, [user?.site_name]);

  useEffect(() => {
    const handleSiteIconUpdated = (event: Event) => {
      setSiteIconUrl((event as CustomEvent<string>).detail || DEFAULT_SITE_ICON_URL);
    };
    window.addEventListener(SITE_ICON_UPDATED_EVENT, handleSiteIconUpdated);
    return () => window.removeEventListener(SITE_ICON_UPDATED_EVENT, handleSiteIconUpdated);
  }, []);

  useEffect(() => {
    const activeGroup = navGroups.find((group) => group.items.some((item) => location.pathname.startsWith(item.path)));
    if (!activeGroup || !collapsedGroups.has(activeGroup.label)) return;
    setCollapsedGroups((currentGroups) => {
      const nextGroups = new Set(currentGroups);
      nextGroups.delete(activeGroup.label);
      return nextGroups;
    });
  }, [location.pathname, collapsedGroups]);

  useEffect(() => {
    window.localStorage.setItem("admin-nav-collapsed", JSON.stringify([...collapsedGroups]));
  }, [collapsedGroups]);

  useEffect(() => {
    document.title = `${current?.label ?? "控制台"} - ${adminName}`;
  }, [adminName, current?.label]);

  function toggleNavGroup(label: string) {
    setCollapsedGroups((currentGroups) => {
      const nextGroups = new Set(currentGroups);
      if (nextGroups.has(label)) {
        nextGroups.delete(label);
      } else {
        nextGroups.add(label);
      }
      return nextGroups;
    });
  }

  useEffect(() => {
    function handleRequestError(event: Event) {
      const detail = (event as CustomEvent<{ message?: string; code?: number }>).detail;
      const message = detail?.message ?? "请求失败，请稍后重试";
      setRequestError(detail?.code ? `${message}（${detail.code}）` : message);
      if (dismissTimer.current) window.clearTimeout(dismissTimer.current);
      dismissTimer.current = window.setTimeout(() => setRequestError(""), 9000);
    }
    window.addEventListener("admin-web:request-error", handleRequestError);
    return () => {
      window.removeEventListener("admin-web:request-error", handleRequestError);
      if (dismissTimer.current) window.clearTimeout(dismissTimer.current);
    };
  }, []);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <img src={siteIconUrl} alt="" />
          </div>
          <div>
            <strong>{adminName}</strong>
            <span>运营管理</span>
          </div>
        </div>

        <nav className="nav-list" aria-label="管理菜单">
          {visibleNavGroups.map((group) => (
            <div className="nav-group" key={group.label}>
              <button
                type="button"
                className="nav-group-trigger"
                onClick={() => toggleNavGroup(group.label)}
                aria-expanded={!collapsedGroups.has(group.label)}
              >
                <span>{group.label}</span>
                <ChevronDown size={14} />
              </button>
              {!collapsedGroups.has(group.label) ? (
                <div className="nav-group-items">
                  {group.items.map((item) => {
                    const Icon = item.icon;
                    return (
                      <NavLink key={item.path} to={item.path} className="nav-item">
                        <Icon size={18} />
                        <span>{item.label}</span>
                      </NavLink>
                    );
                  })}
                </div>
              ) : null}
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          <Settings2 size={18} />
          <span>系统配置预留</span>
        </div>
      </aside>

      <div className="main-area">
        <header className="topbar">
          <div className="topbar-title">
            <button className="icon-button mobile-only" aria-label="展开菜单">
              <Menu size={18} />
            </button>
            <div>
              <span className="breadcrumb">{adminName} / {current?.label ?? "控制台"}</span>
              <h1>{current?.label ?? "控制台"}</h1>
            </div>
          </div>

          <div className="topbar-actions">
            <button
              className="icon-button"
              type="button"
              aria-label={themeMode === "dark" ? "切换浅色主题" : "切换深色主题"}
              onClick={toggleThemeMode}
            >
              {themeMode === "dark" ? <Sun size={18} /> : <Moon size={18} />}
            </button>
            <button className="icon-button" aria-label="通知">
              <Bell size={18} />
              <span className="notification-dot" />
            </button>
            <div className="user-chip">
              <div className="avatar">{user?.username.slice(0, 1).toUpperCase()}</div>
              <div>
                <strong>{user?.username}</strong>
                <span>{user ? roleLabel[user.role] : ""}</span>
              </div>
            </div>
            <button className="secondary-button" onClick={logout}>
              <LogOut size={16} />
              退出
            </button>
          </div>
        </header>

        <main className="content">
          {requestError ? (
            <div className="global-error-banner" role="alert">
              <AlertTriangle size={18} />
              <span>{requestError}</span>
              <button type="button" onClick={() => setRequestError("")} aria-label="关闭错误提示"><X size={16} /></button>
            </div>
          ) : null}
          <Outlet />
        </main>
      </div>
    </div>
  );
}
