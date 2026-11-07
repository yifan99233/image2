import type { LucideIcon } from "lucide-react";

export type NavigationItem = {
  label: string;
  path: string;
  icon: LucideIcon;
  badge?: string;
  moduleKey?: string;
};

export type NavigationGroup = {
  label: string;
  items: NavigationItem[];
  moduleKey?: string;
};
