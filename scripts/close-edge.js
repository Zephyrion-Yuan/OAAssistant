import { closeAllEdgeProcesses } from '../src/profile/profileCache.js';

const result = closeAllEdgeProcesses();
console.log(JSON.stringify(result, null, 2));

if (!result.ok) {
  process.exitCode = 1;
}
