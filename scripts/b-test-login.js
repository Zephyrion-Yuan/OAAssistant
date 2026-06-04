import { closeEdgeBackgroundProcesses } from '../src/profile/profileCache.js';
import { testCachedProfileLogin } from '../src/profile/testLogin.js';

try {
  const cleanup = closeEdgeBackgroundProcesses();
  if (!cleanup.ok) {
    console.error(JSON.stringify(cleanup, null, 2));
    process.exit(1);
  }
  const result = await testCachedProfileLogin();
  console.log(JSON.stringify({ cleanup, result }, null, 2));
  process.exit(result.ok ? 0 : 2);
} catch (error) {
  console.error(error.stack || error.message);
  process.exit(1);
}
