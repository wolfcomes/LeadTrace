import { enAiConsole } from './en-ai-console';
import { enProvenance } from './en-provenance';
import { ref } from 'vue';
import { enCommon } from './en-common';
import { enWorkbench } from './en-workbench';
import { enReview } from './en-review';

export type Locale = 'zh-CN' | 'en';
export const LOCALE_STORAGE_KEY = 'leadtrace.locale';
export const locale = ref<Locale>('zh-CN');
const english: Readonly<Record<string, string>> = { ...enCommon, ...enReview, ...enWorkbench, ...enProvenance, ...enAiConsole };

export function setLocale(next: Locale): void {
  if (next !== 'zh-CN' && next !== 'en') return;
  locale.value = next;
  if (typeof document !== 'undefined') document.documentElement.lang = next;
  try { localStorage.setItem(LOCALE_STORAGE_KEY, next); } catch { /* Storage may be disabled. */ }
}

export function restoreLocale(): void {
  let stored: string | null = null;
  try { stored = localStorage.getItem(LOCALE_STORAGE_KEY); } catch { /* Keep the default. */ }
  setLocale(stored === 'en' ? 'en' : 'zh-CN');
}

/** Translate interface copy only. Scientific records and free-form user text stay untouched. */
export function t(source: string, params?: Record<string, string | number>): string {
  const translated = locale.value === 'en' ? english[source] ?? source : source;
  return params ? translated.replace(/\{(\w+)\}/g, (token, key: string) => String(params[key] ?? token)) : translated;
}

export function formatNumber(value: number, options?: Intl.NumberFormatOptions): string {
  return new Intl.NumberFormat(locale.value, options).format(value);
}

export function formatDate(value: string | number | Date, options?: Intl.DateTimeFormatOptions): string {
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat(locale.value, options ?? { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}
