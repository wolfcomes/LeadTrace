import vue from "@vitejs/plugin-vue";
import { resolve } from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [vue()],
  define: {
    global: "globalThis",
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
  },
  build: {
    commonjsOptions: {
      transformMixedEsModules: true,
    },
    rollupOptions: {
      input: {
        index: resolve(import.meta.dirname, "index.html"),
        ketcher: resolve(import.meta.dirname, "ketcher.html"),
      },
    },
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.spec.ts"],
  },
});
