import { NavLink, Link } from "react-router-dom";
import { useEffect, useState } from "react";
import { ChevronDown, ChevronLeft, Headphones, MessageSquareText } from "lucide-react";
import { clsx } from "clsx";
import { navigationGroups } from "@/config/navigation";
import { Button } from "@/components/ui/Button";
import { loadSiteConfig, readCachedSiteConfig } from "@/services/siteConfigStore";

type SidebarProps = {
  collapsed: boolean;
  mobileOpen?: boolean;
  onNavigate?: () => void;
  onToggle: () => void;
};

export const Sidebar = ({ collapsed, mobileOpen = false, onToggle, onNavigate }: SidebarProps) => {
  const [collapsedGroups, setCollapsedGroups] = useState<string[]>([]);
  const [siteConfig, setSiteConfig] = useState(readCachedSiteConfig);

  useEffect(() => {
    let ignore = false;
    loadSiteConfig().then((config) => {
      if (!ignore) setSiteConfig(config);
    });
    return () => {
      ignore = true;
    };
  }, []);

  const toggleGroup = (label: string) => {
    setCollapsedGroups((groups) => (groups.includes(label) ? groups.filter((group) => group !== label) : [...groups, label]));
  };
  const enabledModules = new Set(siteConfig.enabled_modules);

  return (
    <aside id="workspace-navigation" className={clsx("sidebar", collapsed && "sidebar--collapsed")}>
      <div className="brand">
        <span className="brand__mark">
          <img src={siteConfig.site_icon_url || "/image2ai-icon.svg"} alt="" />
        </span>
        <span className="brand__copy">
          <strong>{siteConfig.site_name}</strong>
          <small>AI 创作工作台</small>
        </span>
        <Button
          className="sidebar__toggle"
          variant="ghost"
          type="button"
          aria-label={mobileOpen ? "关闭导航" : collapsed ? "展开导航" : "折叠导航"}
          onClick={onToggle}
        >
          <ChevronLeft size={18} />
        </Button>
      </div>

      <nav className="sidebar__nav" aria-label="主导航">
        {navigationGroups.map((group) => {
          if (group.moduleKey && !enabledModules.has(group.moduleKey)) return null;
          const visibleItems = group.items.filter((item) => !item.moduleKey || enabledModules.has(item.moduleKey));
          if (!visibleItems.length) return null;
          const isGroupCollapsed = !collapsed && collapsedGroups.includes(group.label);

          return (
            <div className={clsx("nav-group", isGroupCollapsed && "nav-group--collapsed")} key={group.label}>
              <button
                className="nav-group__label"
                type="button"
                aria-expanded={!isGroupCollapsed}
                onClick={() => toggleGroup(group.label)}
              >
                <span>{group.label}</span>
                <ChevronDown size={15} />
              </button>
              <div className="nav-group__items">
                {visibleItems.map((item) => {
                  const Icon = item.icon;

                  return (
                    <NavLink
                      className={({ isActive }) => clsx("nav-item", isActive && "nav-item--active")}
                      key={item.path}
                      to={item.path}
                      title={item.label}
                      onClick={onNavigate}
                    >
                      <span className="nav-item__icon" aria-hidden="true"><Icon size={20} /></span>
                      <span className="nav-item__text">{item.label}</span>
                      {item.badge ? <em>{item.badge}</em> : null}
                    </NavLink>
                  );
                })}
              </div>
            </div>
          );
        })}
        <div className="sidebar__mobile-tools">
          {enabledModules.has("support") && <Link to="/support" onClick={onNavigate}><Headphones size={18} />联系客服</Link>}
          {enabledModules.has("feedback") && <Link to="/feedback" onClick={onNavigate}><MessageSquareText size={18} />意见反馈</Link>}
        </div>
      </nav>
    </aside>
  );
};
