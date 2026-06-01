const statusBox = document.querySelector('#sessionStatus');
const loginShot = document.querySelector('#loginScreenshot');
const serviceBadge = document.querySelector('#serviceBadge');
const oaBadge = document.querySelector('#oaBadge');
const pdmBadge = document.querySelector('#pdmBadge');

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

function setBadge(element, state, text) {
  element.className = `badge ${state}`;
  element.textContent = text;
}

async function api(path, payload = null) {
  const options = payload
    ? {
        method: 'POST',
        headers: { 'Content-Type': 'application/json; charset=utf-8' },
        body: JSON.stringify(payload)
      }
    : {};
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

function showLoginScreenshot(result) {
  const screenshotUrl = result?.screenshotUrl || result?.lastLoginScreenshot?.url;
  if (!screenshotUrl) return;
  loginShot.src = screenshotUrl;
  loginShot.hidden = false;
}

async function refreshStatus() {
  const status = await api('/api/session/status');
  statusBox.textContent = pretty(status);
  showLoginScreenshot(status?.oaLiveSession);

  setBadge(serviceBadge, 'ok', '服务正常');
  document.querySelector('#browserState').textContent = status.oaLiveSession?.browser || '-';
  document.querySelector('#profileMode').textContent = status.oaLiveSession?.profile?.mode || '-';
  document.querySelector('#runtimeDir').textContent = status.oaLiveSession?.runtimeDir || '-';
  document.querySelector('#pdmCacheState').textContent = status.pdmCachedSession?.cache?.exists ? '已缓存' : '未缓存';
}

async function runWithOutput(output, fn) {
  try {
    output.textContent = 'running...';
    const result = await fn();
    output.textContent = pretty(result);
    return result;
  } catch (error) {
    output.textContent = error.stack || error.message;
    throw error;
  }
}

document.querySelector('#refreshStatus').addEventListener('click', refreshStatus);

document.querySelector('#startOaLogin').addEventListener('click', async () => {
  const output = document.querySelector('#oaLoginOutput');
  const result = await runWithOutput(output, () => api('/api/oa/login/start', {}));
  showLoginScreenshot(result);
  setBadge(oaBadge, result.login?.requiresLogin ? 'warn' : 'ok', result.login?.requiresLogin ? '待扫码' : '已登录');
  await refreshStatus();
});

document.querySelector('#testOaLive').addEventListener('click', async () => {
  const output = document.querySelector('#oaLoginOutput');
  const result = await runWithOutput(output, () => api('/api/oa/login/test-live', {}));
  setBadge(oaBadge, result.ok ? 'ok' : 'bad', result.ok ? '有效' : '失效');
  await refreshStatus();
});

document.querySelector('#startPdmLogin').addEventListener('click', async () => {
  const output = document.querySelector('#pdmLoginOutput');
  const result = await runWithOutput(output, () => api('/api/pdm/login/start', {}));
  showLoginScreenshot(result);
  setBadge(pdmBadge, result.login?.requiresLogin ? 'warn' : 'ok', result.login?.requiresLogin ? '待登录' : '已登录');
  await refreshStatus();
});

document.querySelector('#testPdmLive').addEventListener('click', async () => {
  const output = document.querySelector('#pdmLoginOutput');
  const result = await runWithOutput(output, () => api('/api/pdm/login/test-live', {}));
  setBadge(pdmBadge, result.ok ? 'ok' : 'bad', result.ok ? '有效' : '失效');
  await refreshStatus();
});

refreshStatus().catch((error) => {
  setBadge(serviceBadge, 'bad', '服务异常');
  statusBox.textContent = error.stack || error.message;
});
