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
    return (
      <main className="screen-center">
        <div className="loading-panel">
          <span className="loading-dot" />
          <p>正在恢复会话</p>
        </div>
      </main>
    );
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
