import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { createPinia } from "pinia";
import { createApp, ref } from "vue";
import { loadPreviewInstance, previewInstanceKey } from "./api/environment";
import "@fontsource-variable/noto-sans-sc";
import "@fontsource-variable/noto-serif-sc";

import App from "./App.vue";
import { restoreLocale } from "./i18n";
import { createAppRouter } from "./app/router";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/components.css";
import "./styles/layouts.css";


restoreLocale();
const application = createApp(App);
const previewInstance = ref<string | null>(null);
application.provide(previewInstanceKey, previewInstance);
void loadPreviewInstance().then((instance) => { previewInstance.value = instance; });
application.use(createPinia());
application.use(createAppRouter());
application.use(VueQueryPlugin, {
  queryClient: new QueryClient({
    defaultOptions: {
      queries: { refetchOnWindowFocus: false, retry: 1 },
    },
  }),
});
application.mount("#app");
