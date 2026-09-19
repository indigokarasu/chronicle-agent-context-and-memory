// Builds dashboard/dist from dashboard/web/src.
//   dist/index.js  - the plugin entry the dashboard host loads on every page (small, no deps)
//   dist/tapestry.js  - the Tapestry navigator, loaded by index.js only when its tab opens (bundles deck.gl)
// Both are IIFEs. React is taken from window.__HERMES_PLUGIN_SDK__ at runtime; nothing imports it.
import { build } from "esbuild";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const dist = resolve(here, "..", "dist");
const common = { bundle: true, format: "iife", target: "es2020", legalComments: "none", logLevel: "info" };

await build({ ...common, entryPoints: [resolve(here, "src/index.js")], outfile: resolve(dist, "index.js"), minify: false });
await build({ ...common, entryPoints: [resolve(here, "src/tapestry/main.js")], outfile: resolve(dist, "tapestry.js"), minify: true });
