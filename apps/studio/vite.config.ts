import { defineConfig } from "vite";
import { viteStaticCopy } from "vite-plugin-static-copy";

const host = process.env.TAURI_DEV_HOST;

export default defineConfig({
  plugins: [
    viteStaticCopy({
      targets: [
        // Vditor appends `/dist/...` to `cdn`; preserve that directory level so
        // the editor, i18n bundle, MathJax and theme assets stay fully local.
        { src: "node_modules/vditor/dist", dest: "vendor/vditor" },
      ],
    }),
  ],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host ? { protocol: "ws", host, port: 1421 } : undefined,
    watch: { ignored: ["**/src-tauri/**", "**/sidecar/**"] },
  },
  envPrefix: ["VITE_", "TAURI_ENV_"],
  build: {
    target: process.env.TAURI_ENV_PLATFORM === "windows" ? "chrome105" : "safari13",
    minify: process.env.TAURI_ENV_DEBUG ? false : "esbuild",
    sourcemap: Boolean(process.env.TAURI_ENV_DEBUG),
  },
});
