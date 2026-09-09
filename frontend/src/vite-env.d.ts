/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_REVIEW_DATA_SOURCE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
