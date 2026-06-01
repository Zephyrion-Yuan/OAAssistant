import { cacheEdgeProfile } from '../src/profile/profileCache.js';

try {
  const result = cacheEdgeProfile({ force: true });
  console.log(JSON.stringify(result, null, 2));
} catch (error) {
  console.error(error.message);
  process.exit(1);
}
