import { redactUrl } from '../src/security/redaction.js';

const rawUrl = process.argv.slice(2).join(' ').trim();
if (!rawUrl) {
  console.error('Usage: node scripts/relay-url.js <url>');
  process.exit(2);
}

const endpoint = process.env.MEGANT_RELAY_ENDPOINT || 'http://127.0.0.1:8787/api/sso/open';

try {
  const response = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify({ url: rawUrl })
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || response.statusText);
  console.log(JSON.stringify({
    ok: true,
    redactedUrl: result.redactedUrl || redactUrl(rawUrl),
    currentUrl: result.currentUrl,
    openedAt: result.openedAt
  }, null, 2));
} catch (error) {
  console.error(JSON.stringify({
    ok: false,
    redactedUrl: redactUrl(rawUrl),
    error: error.message
  }, null, 2));
  process.exit(1);
}
