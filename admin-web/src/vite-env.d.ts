/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_ADMIN_API_BASE_URL?: string;
  readonly VITE_SITE_FRONTEND_ROOT_DOMAIN?: string;
  readonly VITE_SITE_ADMIN_ROOT_DOMAIN?: string;
  readonly VITE_SITE_FRONTEND_BASE_SUBDOMAIN?: string;
  readonly VITE_SITE_ADMIN_BASE_SUBDOMAIN?: string;
  readonly VITE_SITE_FRONTEND_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
