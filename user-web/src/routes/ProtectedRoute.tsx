import { SessionLoading } from "@/components/ui/SessionLoading";
import { useEffect, useState } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuthStore } from "@/stores/authStore";

export const ProtectedRoute = () => {
  const location = useLocation();
  const status = useAuthStore((state) => state.status);
  const [sessionExpired, setSessionExpired] = useState(false);

  useEffect(() => {
    const handleExpiredSession = () => setSessionExpired(true);
    window.addEventListener("image2:session-expired", handleExpiredSession);

    return () => {
      window.removeEventListener("image2:session-expired", handleExpiredSession);
    };
  }, []);

  if (status === "idle" || status === "checking") {
    return <SessionLoading />;
  }

  if (status !== "authenticated") {
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: location, sessionExpired: sessionExpired || undefined }}
      />
    );
  }

  return <Outlet />;
};
