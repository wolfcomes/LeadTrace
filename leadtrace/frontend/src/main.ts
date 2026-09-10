import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "./App.vue";


const application = createApp(App);
application.use(createPinia());
application.use(VueQueryPlugin, {
  queryClient: new QueryClient({
    defaultOptions: {
      queries: { refetchOnWindowFocus: false, retry: 1 },
    },
  }),
});
application.mount("#app");
