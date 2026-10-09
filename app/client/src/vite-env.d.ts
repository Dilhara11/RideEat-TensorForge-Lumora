/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the API engine, e.g. "https://api.example.com". Set at build time (Amplify env var). Empty = same origin (dev proxy). */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
