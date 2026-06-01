import { testPdmCachedProfileLogin } from '../src/profile/testLogin.js';

try {
  const result = await testPdmCachedProfileLogin();
  console.log(JSON.stringify(result, null, 2));
  process.exit(result.ok ? 0 : 2);
} catch (error) {
  console.error(error.stack || error.message);
  process.exit(1);
}
