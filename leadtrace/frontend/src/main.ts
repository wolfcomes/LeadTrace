import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { createPinia } from "pinia";
import { createApp } from "vue";
import "@fontsource-variable/noto-sans-sc";
import "@fontsource-variable/noto-serif-sc";

import App from "./App.vue";
import { createAppRouter } from "./app/router";
import "./styles/tokens.css";


const application = createApp(App);
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
