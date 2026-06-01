import { cacheEdgeProfile, closeEdgeBackgroundProcesses } from '../src/profile/profileCache.js';

const cleanup = closeEdgeBackgroundProcesses();
if (!cleanup.ok) {
  console.error(JSON.stringify(cleanup, null, 2));
  process.exit(1);
}
const cache = cacheEdgeProfile({ force: true });
console.log(JSON.stringify({ cleanup, cache }, null, 2));
