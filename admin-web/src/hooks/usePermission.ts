import { hasPermission, type Permission } from "../lib/permissions";
import { useAuth } from "../store/auth";

export function usePermission() {
  const { user } = useAuth();

  return {
    can: (permission: Permission) => hasPermission(user, permission),
  };
}
