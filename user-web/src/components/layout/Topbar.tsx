import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  ChevronDown,
  ChevronRight,
  Coins,
  Gift,
  Headphones,
  KeyRound,
  LogOut,
  LayoutGrid,
  Menu,
  MessageSquareText,
  Moon,
  Settings,
  Sun,
  UserRound,
  UsersRound,
} from "lucide-react";
import { navigationGroups, topbarActionLinks, utilityLinks } from "@/config/navigation";
import { Button } from "@/components/ui/Button";
import { creditService } from "@/services/credits";
import { inviteService } from "@/services/invite";
import { rewardService } from "@/services/rewards";
import { loadSiteConfig, readCachedSiteConfig } from "@/services/siteConfigStore";
import { useAuthStore } from "@/stores/authStore";
import { useThemeStore } from "@/stores/themeStore";
import type { CreditBalance } from "@/types/api";
import { CREDIT_BALANCE_CHANGED_EVENT } from "@/utils/creditEvents";
import { rechargePath } from "@/utils/rechargeAccess";

export const Topbar = ({
  onToggleNavigation,
  navigationOpen = false,
}: {
  onToggleNavigation?: () => void;
  navigationOpen?: boolean;
}) => {
  const navigate = useNavigate();
  const location = useLocation();
  const currentNavigation = navigationGroups.flatMap((group) => group.items).find((item) => item.path === location.pathname);
  const CurrentPageIcon = currentNavigation?.icon ?? LayoutGrid;
  const currentPage =
    navigationGroups.flatMap((group) => group.items).find((item) => item.path === location.pathname)
      ?.label ??
    topbarActionLinks.find((item) => item.path === location.pathname)?.label ??
    "个人中心";
  const menuRef = useRef<HTMLDivElement>(null);
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);
  const themeMode = useThemeStore((state) => state.themeMode);
  const toggleTheme = useThemeStore((state) => state.toggleTheme);
  const [balance, setBalance] = useState<CreditBalance | null>(null);
  const [balanceError, setBalanceError] = useState<string | null>(null);
  const [isSigninRewardEnabled, setIsSigninRewardEnabled] = useState(false);
  const [isInviteRewardEnabled, setIsInviteRewardEnabled] = useState(false);
  const [siteConfig, setSiteConfig] = useState(readCachedSiteConfig);
  const [isMenuOpen, setIsMenuOpen] = useState(false);

  const displayName = useMemo(() => user?.nickname || user?.username || "用户", [user]);

  useEffect(() => {
    let ignore = false;

    const loadBalance = async () => {
      try {
        const creditBalance = await creditService.getBalance();

        if (!ignore) {
          setBalance(creditBalance);
          setBalanceError(null);
        }
      } catch (error) {
        if (!ignore) {
          setBalanceError(error instanceof Error ? error.message : "积分加载失败");
        }
      }
    };

    void loadBalance();
    window.addEventListener(CREDIT_BALANCE_CHANGED_EVENT, loadBalance);

    return () => {
      ignore = true;
      window.removeEventListener(CREDIT_BALANCE_CHANGED_EVENT, loadBalance);
    };
  }, []);

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
    let ignore = false;
    rewardService
      .getSigninStatus()
      .then((config) => {
        if (!ignore) setIsSigninRewardEnabled(config.is_enabled);
      })
      .catch(() => {
        if (!ignore) setIsSigninRewardEnabled(false);
      });
    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    let ignore = false;
    inviteService
      .getRewardConfig()
      .then((config) => {
        if (!ignore) setIsInviteRewardEnabled(config.is_enabled);
      })
      .catch(() => {
        if (!ignore) setIsInviteRewardEnabled(false);
      });
    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    const closeOnPointerDown = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) {
        setIsMenuOpen(false);
      }
    };

    document.addEventListener("mousedown", closeOnPointerDown);

    return () => {
      document.removeEventListener("mousedown", closeOnPointerDown);
    };
  }, []);

  const handleLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };
  const enabledModules = new Set(siteConfig.enabled_modules);
  const rechargeTarget = rechargePath(siteConfig);

  return (
    <header className="topbar">
      <div className="topbar__links">
        <button
          className="topbar__mobile-menu"
          type="button"
          aria-label={navigationOpen ? "关闭导航" : "打开导航"}
          aria-expanded={navigationOpen}
          aria-controls="workspace-navigation"
          onClick={onToggleNavigation}
        >
          <Menu size={20} />
        </button>
        <nav className="topbar__breadcrumb" aria-label="当前位置">
          <LayoutGrid size={17} aria-hidden="true" />
          <span>工作空间</span>
          <ChevronRight size={13} />
          <strong aria-current="page"><CurrentPageIcon size={16} aria-hidden="true" /><span>{currentPage}</span></strong>
        </nav>
        {utilityLinks.map((link, index) => {
          const isOpenClaw = link.label.includes("OpenClaw");
          const isTeam = link.label === "团队版";

          return (
            <Link
              className={isOpenClaw ? "topbar-link topbar-link--success" : "topbar-link"}
              key={link.path}
              to={link.path}
            >
              {index === 0 ? <KeyRound size={14} /> : null}
              <span>{link.label}</span>
              {isOpenClaw ? <strong>NEW</strong> : null}
              {isTeam ? <em>团队版</em> : null}
            </Link>
          );
        })}
      </div>

      <div className="topbar__actions">
        <Button
          className="icon-button topbar-moon"
          variant="ghost"
          type="button"
          aria-label={themeMode === "dark" ? "切换浅色主题" : "切换深色主题"}
          onClick={toggleTheme}
        >
          {themeMode === "dark" ? <Sun size={18} /> : <Moon size={18} />}
        </Button>

        {topbarActionLinks
          .filter((link) => enabledModules.has(link.moduleKey))
          .filter((link) => link.path !== "/rewards/signin" || isSigninRewardEnabled)
          .filter((link) => link.path !== "/rewards/invite" || isInviteRewardEnabled)
          .map((link) => (
            <Link
              className={`top-action top-action--${link.tone}`}
              key={link.path}
              to={link.path}
              title={link.label}
              aria-label={link.label}
            >
              {link.path === "/feedback" ? (
                <MessageSquareText size={15} />
              ) : link.tone === "neutral" ? (
                <Headphones size={15} />
              ) : (
                <Gift size={15} />
              )}
              <span>{link.label}</span>
            </Link>
          ))}

        {enabledModules.has("recharge") ? (
          <Link
            className="credit-pill"
            to={rechargeTarget}
            title={balanceError ?? "当前积分余额"}
          >
            <Coins size={17} />
            <span>{balance ? balance.balance.toLocaleString() : "--"}</span>
          </Link>
        ) : null}

        <div className="account-menu" ref={menuRef}>
          <Button
            className="account-menu__trigger"
            variant="ghost"
            type="button"
            aria-label="账户菜单"
            aria-expanded={isMenuOpen}
            onClick={() => setIsMenuOpen((isOpen) => !isOpen)}
          >
            <span className="avatar">{displayName.slice(0, 1).toUpperCase()}</span>
            <span>{displayName}</span>
            <ChevronDown size={16} />
          </Button>

          {isMenuOpen ? (
            <div className="account-menu__panel" role="menu">
              <div className="account-menu__mobile-links">
                {enabledModules.has("recharge") && (
                  <Link to={rechargeTarget} role="menuitem" onClick={() => setIsMenuOpen(false)}>
                    <Coins size={16} />
                    充值积分
                  </Link>
                )}
                {topbarActionLinks
                  .filter((link) => enabledModules.has(link.moduleKey))
                  .filter((link) => link.path !== "/rewards/signin" || isSigninRewardEnabled)
                  .filter((link) => link.path !== "/rewards/invite" || isInviteRewardEnabled)
                  .map((link) => (
                    <Link
                      key={link.path}
                      to={link.path}
                      role="menuitem"
                      onClick={() => setIsMenuOpen(false)}
                    >
                      {link.path === "/feedback" ? (
                        <MessageSquareText size={16} />
                      ) : link.path === "/support" ? (
                        <Headphones size={16} />
                      ) : (
                        <Gift size={16} />
                      )}
                      {link.label}
                    </Link>
                  ))}
              </div>
              <Link to="/account/profile" role="menuitem" onClick={() => setIsMenuOpen(false)}>
                <UserRound size={16} />
                个人资料
              </Link>
              <Link to="/account/settings" role="menuitem" onClick={() => setIsMenuOpen(false)}>
                <Settings size={16} />
                账号设置
              </Link>
              <Link to="/credits/ledger" role="menuitem" onClick={() => setIsMenuOpen(false)}>
                <Coins size={16} />
                积分记录
              </Link>
              <Link to="/team" role="menuitem" onClick={() => setIsMenuOpen(false)}>
                <UsersRound size={16} />
                切换个人 / 团队版
              </Link>
              <button type="button" role="menuitem" onClick={handleLogout}>
                <LogOut size={16} />
                退出登录
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </header>
  );
};
