import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "@/routes/App";
import { registerUnauthorizedHandler } from "@/services/http";
import { useAuthStore } from "@/stores/authStore";
import "@/theme/styles.css";

registerUnauthorizedHandler(() => {
  useAuthStore.getState().logout();
  window.dispatchEvent(new CustomEvent("image2:session-expired"));
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
