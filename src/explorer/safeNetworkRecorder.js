import { redactText, redactUrl, sensitiveNamePattern } from '../security/redaction.js';

const listPaths = [
  ['data', 'list'],
  ['data', 'records'],
  ['data', 'rows'],
  ['data', 'items'],
  ['list'],
  ['records'],
  ['rows'],
  ['items']
];

function isSensitiveKey(key) {
  return sensitiveNamePattern.test(String(key || ''));
}

function scalarSample(value) {
  if (value === null || value === undefined) return value;
  if (typeof value === 'string') return redactText(value).slice(0, 160);
  if (typeof value === 'number' || typeof value === 'boolean') return value;
  return String(value).slice(0, 80);
}

function summarizeValue(value, depth = 0) {
  if (depth > 4) return { type: Array.isArray(value) ? 'array' : typeof value };
  if (Array.isArray(value)) {
    const firstObject = value.find((item) => item && typeof item === 'object' && !Array.isArray(item));
    return {
      type: 'array',
      length: value.length,
      itemKeys: firstObject ? Object.keys(firstObject).slice(0, 80) : [],
      sample: value.slice(0, 3).map((item) => summarizeValue(item, depth + 1))
    };
  }
  if (value && typeof value === 'object') {
    const shape = {};
    for (const [key, item] of Object.entries(value).slice(0, 80)) {
      shape[key] = isSensitiveKey(key) ? '[redacted]' : summarizeValue(item, depth + 1);
    }
    return {
      type: 'object',
      keys: Object.keys(value).slice(0, 120),
      shape
    };
  }
  return {
    type: value === null ? 'null' : typeof value,
    sample: scalarSample(value)
  };
}

function getPath(root, pathParts) {
  let current = root;
  for (const part of pathParts) {
    if (!current || typeof current !== 'object') return null;
    current = current[part];
  }
  return current;
}

function findListCandidates(body) {
  return listPaths
    .map((pathParts) => {
      const value = getPath(body, pathParts);
      if (!Array.isArray(value)) return null;
      const firstObject = value.find((item) => item && typeof item === 'object' && !Array.isArray(item));
      return {
        path: pathParts.join('.'),
        length: value.length,
        itemKeys: firstObject ? Object.keys(firstObject).slice(0, 120) : []
      };
    })
    .filter(Boolean);
}

function parseBody(text, contentType = '') {
  const trimmed = String(text || '').trim();
  if (!trimmed) return null;
  if (/json/i.test(contentType) || /^[{[]/.test(trimmed)) {
    try {
      return JSON.parse(trimmed);
    } catch {
      return { text: redactText(trimmed).slice(0, 500) };
    }
  }
  if (/application\/x-www-form-urlencoded/i.test(contentType)) {
    const params = new URLSearchParams(trimmed);
    const value = {};
    for (const [key, item] of params.entries()) {
      value[key] = isSensitiveKey(key) ? '[redacted]' : redactText(item).slice(0, 160);
    }
    return value;
  }
  return { text: redactText(trimmed).slice(0, 500) };
}

function summarizeRequestPostData(request) {
  const postData = request.postData();
  if (!postData) return null;
  const contentType = request.headers()['content-type'] || '';
  const parsed = parseBody(postData, contentType);
  return summarizeValue(parsed);
}

async function summarizeResponseBody(response) {
  const contentType = response.headers()['content-type'] || '';
  if (!/json|text/i.test(contentType)) return null;
  const contentLength = Number(response.headers()['content-length'] || 0);
  if (contentLength > 1_000_000) {
    return { skipped: true, reason: 'Response body is larger than 1MB.' };
  }
  const text = await response.text().catch(() => '');
  if (!text) return null;
  const parsed = parseBody(text, contentType);
  const summary = summarizeValue(parsed);
  return {
    contentType,
    summary,
    listCandidates: parsed && typeof parsed === 'object' ? findListCandidates(parsed) : []
  };
}

function classifyApiCall(entry) {
  const lists = entry.responseBody?.listCandidates || [];
  const statusOk = entry.status >= 200 && entry.status < 300;
  return {
    dataQueryCandidate: statusOk && lists.length > 0,
    independentCandidate: statusOk && lists.length > 0 && ['GET', 'POST'].includes(entry.method),
    reason: lists.length > 0 ? 'JSON response contains list-like data.' : 'No list-like response detected.'
  };
}

export function attachSafeNetworkRecorder(page) {
  const calls = [];
  const byRequest = new Map();
  let phase = 'initial-load';

  page.on('request', (request) => {
    if (!['xhr', 'fetch'].includes(request.resourceType())) return;
    const entry = {
      id: calls.length + 1,
      phase,
      method: request.method(),
      redactedUrl: redactUrl(request.url()),
      resourceType: request.resourceType(),
      postDataSummary: summarizeRequestPostData(request),
      startedAt: new Date().toISOString()
    };
    byRequest.set(request, entry);
    calls.push(entry);
  });

  page.on('requestfinished', async (request) => {
    const entry = byRequest.get(request);
    if (!entry) return;
    const response = await request.response().catch(() => null);
    entry.status = response?.status() || null;
    entry.finishedAt = new Date().toISOString();
    if (response) {
      entry.responseBody = await summarizeResponseBody(response);
      entry.classification = classifyApiCall(entry);
    }
  });

  page.on('requestfailed', (request) => {
    const entry = byRequest.get(request);
    if (!entry) return;
    entry.failed = redactText(request.failure()?.errorText || 'request failed');
    entry.finishedAt = new Date().toISOString();
  });

  return {
    calls,
    setPhase(nextPhase) {
      phase = String(nextPhase || 'interaction');
    },
    count() {
      return calls.length;
    }
  };
}
