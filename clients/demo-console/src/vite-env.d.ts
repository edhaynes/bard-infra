/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_REGISTRY_BASE?: string;
  readonly VITE_ROUTER_BASE?: string;
  readonly VITE_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
