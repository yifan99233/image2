import type { AdminUser } from "../types";

export type Permission =
  | "dashboard:read"
  | "site_config:write"
  | "site_content:write"
  | "announcements:write"
  | "admin_accounts:write"
  | "users:read"
  | "users:ownership:write"
  | "users:password:reset"
  | "users:impersonate"
  | "feedbacks:write"
  | "lead_applications:write"
  | "credits:read"
  | "recharge:write"
  | "agent:write"
  | "openagent_releases:write"
  | "models:write"
  | "model_prices:write"
  | "materials:write"
  | "tasks:write"
  | "ux_config:write"
  | "audit:read";

const systemSuperAdminPermissions: Permission[] = [
  "dashboard:read",
  "site_config:write",
  "site_content:write",
  "announcements:write",
  "admin_accounts:write",
  "users:read",
  "users:ownership:write",
  "users:password:reset",
  "users:impersonate",
  "feedbacks:write",
  "lead_applications:write",
  "credits:read",
  "recharge:write",
  "agent:write",
  "openagent_releases:write",
  "models:write",
  "model_prices:write",
  "materials:write",
  "tasks:write",
  "ux_config:write",
  "audit:read",
];

const rolePermissions: Record<AdminUser["role"], Permission[]> = {
  super_admin: [
    "dashboard:read",
    "site_content:write",
    "announcements:write",
    "admin_accounts:write",
    "users:read",
    "users:ownership:write",
    "users:password:reset",
    "feedbacks:write",
    "lead_applications:write",
    "credits:read",
    "recharge:write",
    "agent:write",
    "openagent_releases:write",
    "models:write",
    "model_prices:write",
    "materials:write",
    "tasks:write",
    "ux_config:write",
    "audit:read",
  ],
  operator: ["dashboard:read", "site_content:write", "announcements:write", "users:read", "users:ownership:write", "users:password:reset", "feedbacks:write", "lead_applications:write", "agent:write", "openagent_releases:write", "materials:write", "tasks:write", "ux_config:write", "audit:read"],
  finance: ["dashboard:read", "site_content:write", "users:read", "credits:read", "recharge:write", "agent:write", "audit:read"],
  model_admin: ["dashboard:read", "site_content:write", "models:write", "model_prices:write", "tasks:write", "ux_config:write", "audit:read"],
};

export function hasPermission(user: AdminUser | null | undefined, permission: Permission) {
  if (!user) return false;
  if (user.system_super_admin) return systemSuperAdminPermissions.includes(permission);
  return rolePermissions[user.role].includes(permission);
}
