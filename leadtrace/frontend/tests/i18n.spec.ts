import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { nextTick } from 'vue';
import { createMemoryHistory } from 'vue-router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import App from '../src/App.vue';
import { enCommon } from '../src/i18n/en-common';
import { enReview } from '../src/i18n/en-review';
import LoginPage from '../src/auth/LoginPage.vue';
import AppShell from '../src/app/AppShell.vue';
import { createAppRouter } from '../src/app/router';
import { useAuthStore } from '../src/auth/store';
import { locale, setLocale, t, restoreLocale, LOCALE_STORAGE_KEY } from '../src/i18n';

describe('interface language', () => {
  beforeEach(() => { localStorage.clear(); setLocale('zh-CN'); setActivePinia(createPinia()); });
  afterEach(() => { setLocale('zh-CN'); localStorage.clear(); });
  it('keeps overlapping dictionary entries consistent', () => {
    for (const key of Object.keys(enCommon)) {
      if (Object.hasOwn(enReview, key)) expect(enReview[key], key).toBe(enCommon[key]);
    }
  });
  it('persists supported languages, updates document language and safely falls back', () => {
    setLocale('en');
    expect(locale.value).toBe('en');
    expect(document.documentElement.lang).toBe('en');
    expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('en');
    expect(t('登录')).toBe('Sign in');
    restoreLocale();
    expect(locale.value).toBe('en');
    expect(t('untranslated scientific identity')).toBe('untranslated scientific identity');
    expect(t('共 {count} 篇', { count: 3 })).toBe('3 articles');
    localStorage.setItem(LOCALE_STORAGE_KEY, 'unsupported');
    restoreLocale();
    expect(locale.value).toBe('zh-CN');
  });
  it('switches login text without replacing input state', async () => {
    const router = createAppRouter(createMemoryHistory());
    await router.push('/login'); await router.isReady();
    const wrapper = mount(LoginPage, { global: { plugins: [router] } });
    await wrapper.get('#username').setValue('reviewer.unfinished');
    await wrapper.get('#password').setValue('unsaved-password');
    const input = wrapper.get('#username').element;
    expect(wrapper.text()).toContain('登录 LeadTrace');
    setLocale('en'); await nextTick();
    expect(wrapper.text()).toContain('Sign in to LeadTrace');
    expect(wrapper.get('#username').element).toBe(input);
    expect((input as HTMLInputElement).value).toBe('reviewer.unfinished');
    expect((wrapper.get('#password').element as HTMLInputElement).value).toBe('unsaved-password');
    wrapper.unmount();
  });
  it('updates existing authenticated navigation but preserves human display names', async () => {
    const router = createAppRouter(createMemoryHistory());
    useAuthStore().acceptSession({ user: { username:'admin', display_name:'管理员自定姓名', role:'admin', must_change_password:false }, csrf_token:'test' });
    await router.push('/papers'); await router.isReady();
    const wrapper = mount(AppShell, { global: { plugins:[router], stubs:{RouterView:true} } });
    expect(wrapper.text()).toContain('用户管理');
    useAuthStore().sessionNotice = '退出登录失败，当前会话仍然有效。请稍后重试。';
    await nextTick();
    expect(wrapper.text()).toContain('退出登录失败');
    setLocale('en'); await nextTick();
    expect(wrapper.text()).toContain('Users');
    expect(wrapper.text()).toContain('Sign-out failed.');
    expect(wrapper.text()).toContain('管理员自定姓名');
    wrapper.unmount();
  });
  it('provides one accessible global switch on login and authenticated routes', async () => {
    const wrapper = mount(App, { global:{ stubs:{RouterView:true} } });
    await wrapper.get('[data-language-switch]').setValue('en');
    expect(locale.value).toBe('en');
    expect(wrapper.get('[data-language-switch]').attributes('aria-label')).toBe('Interface language');
    wrapper.unmount();
  });
});
