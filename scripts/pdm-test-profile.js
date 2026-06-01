import { closeEdgeBackgroundProcesses } from '../src/profile/profileCache.js';
import { testPdmCachedProfileLogin } from '../src/profile/testLogin.js';

const cleanup = closeEdgeBackgroundProcesses();
if (!cleanup.ok) {
  console.error(JSON.stringify(cleanup, null, 2));
  process.exit(1);
}
const result = await testPdmCachedProfileLogin();
console.log(JSON.stringify({ cleanup, result }, null, 2));
process.exit(result.ok ? 0 : 1);
