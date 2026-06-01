const sensitiveQueryKeys = new Set([
  'access_token',
  'authcode',
  'auth_code',
  'authorization',
  'code',
  'key',
  '_key',
  'id_token',
  'mfa',
  'password',
  'refresh_token',
  'relaystate',
  'samlresponse',
  'session',
  'sid',
  'state',
  'secret',
  'ticket',
  'token'
]);

export const sensitiveNamePattern = /token|ticket|sid|session|cookie|authorization|password|passwd|secret|key|authcode|auth_code|mfa|samlresponse|relaystate/i;

function shouldRedactQueryKey(key) {
  const lower = key.toLowerCase();
  const normalized = lower.replace(/[-_]/g, '');
  return sensitiveQueryKeys.has(lower) || sensitiveQueryKeys.has(normalized);
}

function redactSearchParams(params) {
  for (const key of Array.from(params.keys())) {
    if (shouldRedactQueryKey(key)) {
      params.set(key, '[redacted]');
    }
  }
}

function redactHashParams(url) {
  if (!url.hash || !url.hash.includes('?')) return;
  const questionIndex = url.hash.indexOf('?');
  const prefix = url.hash.slice(0, questionIndex + 1);
  const params = new URLSearchParams(url.hash.slice(questionIndex + 1));
  redactSearchParams(params);
  url.hash = `${prefix}${params.toString()}`;
}

export function redactUrl(rawUrl) {
  try {
    const url = new URL(rawUrl);
    redactSearchParams(url.searchParams);
    redactHashParams(url);
    return url.toString();
  } catch {
    return String(rawUrl || '').replace(/((?:authCode|auth_code|code|token|ticket|session|state|SAMLResponse|RelayState|_key|key)=)[^&\s]+/gi, '$1[redacted]');
  }
}

export function redactText(text) {
  return String(text || '')
    .replace(/((?:authCode|auth_code|code|token|ticket|session)=)[^&\s]+/gi, '$1[redacted]')
    .replace(/(["']?(?:access_)?token["']?\s*[:=]\s*["'])[^"']+/gi, '$1[redacted]')
    .replace(/(["']?(?:session|ticket|password|secret|code)["']?\s*[:=]\s*["'])[^"']+/gi, '$1[redacted]')
    .replace(/(Bearer\s+)[A-Za-z0-9._-]+/gi, '$1[redacted]');
}
