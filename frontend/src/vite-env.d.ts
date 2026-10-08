/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Базовый адрес API. Пусто в рабочей среде: тот же домен, что и интерфейс. */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}