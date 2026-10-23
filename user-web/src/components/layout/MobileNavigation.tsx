import { Menu } from "lucide-react";
import { GalleryHorizontalEnd, Home, Wand2 } from "@/components/ui/StudioIcons";
import { Link, useLocation } from "react-router-dom";

type Props = {
  enabledModules: string[];
  onOpenMenu: () => void;
  menuOpen: boolean;
};

export function MobileNavigation({ enabledModules, onOpenMenu, menuOpen }: Props) {
  const { pathname } = useLocation();
  const modules = new Set(enabledModules);
  const createPath = [
    ["image_edit", "/create/edit"],
    ["text_to_image", "/create/text-to-image"],
    ["batch_generate", "/create/batch-generate"],
    ["batch_edit", "/create/batch-edit"],
    ["text_to_video", "/create/text-to-video"],
    ["image_to_video", "/create/image-to-video"],
  ].find(([module]) => modules.has(module))?.[1];
  const links = [
    ...(modules.has("dashboard")
      ? [{ label: "首页", path: "/dashboard", icon: Home, active: pathname === "/dashboard" }]
      : []),
    ...(createPath
      ? [
          {
            label: "创作",
            path: pathname.startsWith("/create/") ? pathname : createPath,
            icon: Wand2,
            active: pathname.startsWith("/create/"),
          },
        ]
      : []),
    ...(modules.has("works")
      ? [
          {
            label: "作品",
            path: "/works",
            icon: GalleryHorizontalEnd,
            active: pathname === "/works",
          },
        ]
      : []),
  ];
  return (
    <nav className="mobile-navigation" aria-label="手机常用导航" inert={menuOpen}>
      {links.map(({ label, path, icon: Icon, active }) => (
        <Link key={path} to={path} aria-current={active ? "page" : undefined}>
          <Icon size={21} strokeWidth={1.8} />
          <span>{label}</span>
        </Link>
      ))}
      <button
        type="button"
        onClick={onOpenMenu}
        aria-label="打开全部功能"
        aria-controls="workspace-navigation"
        aria-expanded={menuOpen}
      >
        <Menu size={21} strokeWidth={1.8} />
        <span>全部</span>
      </button>
    </nav>
  );
}
