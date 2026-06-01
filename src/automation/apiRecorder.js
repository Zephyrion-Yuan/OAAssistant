function shouldCaptureBody(url) {
  return [
    '/api/workflow/reqform/loadForm',
    '/api/workflow/reqform/',
    '/api/workflow/request/',
    '/api/workflow/layout/'
  ].some((pattern) => url.includes(pattern));
}

async function captureResponseBody(response) {
  const contentType = response.headers()['content-type'] || '';
  if (!/json|text|html|javascript/i.test(contentType)) return null;
  const text = await response.text().catch(() => '');
  if (!text) return null;
  try {
    return {
      type: 'json',
      value: JSON.parse(text)
    };
  } catch {
    return {
      type: 'text',
      value: text.replace(/\s+/g, ' ').slice(0, 3000)
    };
  }
}

export function attachApiRecorder(page) {
  const calls = [];
  const byRequest = new Map();

  page.on('request', (request) => {
    const resourceType = request.resourceType();
    if (!['xhr', 'fetch'].includes(resourceType)) return;
    const entry = {
      method: request.method(),
      url: request.url(),
      resourceType,
      postData: request.postData() || null,
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
    if (response && shouldCaptureBody(request.url())) {
      entry.responseBody = await captureResponseBody(response);
    }
  });

  page.on('requestfailed', (request) => {
    const entry = byRequest.get(request);
    if (!entry) return;
    entry.failed = request.failure()?.errorText || 'request failed';
    entry.finishedAt = new Date().toISOString();
  });

  return calls;
}
