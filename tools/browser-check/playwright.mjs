/* One place that knows where playwright lives.
 *
 * Both checkers imported it by absolute path, and when the repo was renamed
 * from "Glad Labs Products" to glad-labs-products every one of those paths
 * broke at once. Resolving it here means a move breaks one file, not five.
 */
import { createRequire } from 'node:module';

const CANDIDATES = [
  'playwright',
  '/home/mattm/glad-labs-website/node_modules/playwright/index.mjs',
];

let mod = null;
const require = createRequire(import.meta.url);
for (const spec of CANDIDATES) {
  try { mod = await import(spec); break; } catch (_) {}
  try { mod = require(spec); break; } catch (_) {}
}
if (!mod) throw new Error('playwright not found — see tools/browser-check/README.md');

export const chromium = mod.chromium;
export const devices = mod.devices;
