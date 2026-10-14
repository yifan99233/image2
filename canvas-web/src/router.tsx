import { createHashRouter, Navigate } from "react-router-dom";
import CanvasPage from "@/pages/canvas";
import CanvasProjectPage from "@/pages/canvas/project";
import { HostShell } from "@/integration/HostShell";
export const router = createHashRouter([{ element: <HostShell />, children: [
    { path: "/", element: <Navigate to="/canvas" replace /> },
    { path: "/canvas", element: <CanvasPage /> },
    { path: "/canvas/:id", element: <CanvasProjectPage /> },
    { path: "*", element: <Navigate to="/canvas" replace /> },
]}]);
