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

// ----- WBS registry -----------------------------------------------------------
const wbsBadge = document.querySelector('#wbsBadge');
const wbsForm = document.querySelector('#wbsForm');
const wbsTableBody = document.querySelector('#wbsTableBody');
const wbsOutput = document.querySelector('#wbsOutput');
const wbsShowArchived = document.querySelector('#wbsShowArchived');

const WBS_COLUMNS = [
  'wbsCode', 'projectDefinition', 'demandFactoryCode', 'costCenter',
  'purchaser', 'mrpController'
];

function wbsFormData() {
  const data = {};
  for (const el of wbsForm.elements) {
    if (!el.name) continue;
    const value = el.value.trim();
    if (value !== '') data[el.name] = value;
  }
  return data;
}

function fillWbsForm(record) {
  for (const el of wbsForm.elements) {
    if (!el.name) continue;
    el.value = record[el.name] ?? (el.name === 'status' ? 'active' : '');
  }
  wbsForm.querySelector('[name="wbsCode"]').focus();
}

function makeActionButton(label, danger, onClick) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = danger ? 'linkBtn danger' : 'linkBtn';
  button.textContent = label;
  button.addEventListener('click', onClick);
  return button;
}

function renderWbsRow(record) {
  const row = document.createElement('tr');
  if (record.status === 'archived') row.className = 'archived';
  for (const key of WBS_COLUMNS) {
    const cell = document.createElement('td');
    cell.textContent = record[key] || '-';
    row.appendChild(cell);
  }
  const location = document.createElement('td');
  location.textContent = [record.stockLocationName, record.stockLocationSapCode].filter(Boolean).join(' / ') || '-';
  row.appendChild(location);
  const offset = document.createElement('td');
  offset.textContent = record.demandDateOffsetDays ?? '-';
  row.appendChild(offset);
  const status = document.createElement('td');
  status.textContent = record.status || 'active';
  row.appendChild(status);

  const actions = document.createElement('td');
  const wrap = document.createElement('div');
  wrap.className = 'rowActions';
  wrap.appendChild(makeActionButton('编辑', false, () => fillWbsForm(record)));
  if (record.status !== 'archived') {
    wrap.appendChild(makeActionButton('归档', false, () => wbsMutate('/api/wbs/archive', { wbsCode: record.wbsCode })));
  }
  // inline two-click delete (no blocking native dialog)
  const del = makeActionButton('删除', true, function handler() {
    if (this.dataset.armed !== '1') {
      this.dataset.armed = '1';
      this.textContent = '确认删除?';
      setTimeout(() => { this.dataset.armed = '0'; this.textContent = '删除'; }, 3000);
      return;
    }
    wbsMutate('/api/wbs/delete', { wbsCode: record.wbsCode });
  });
  wrap.appendChild(del);
  actions.appendChild(wrap);
  row.appendChild(actions);
  return row;
}

async function loadWbs() {
  const includeArchived = wbsShowArchived.checked ? '?includeArchived=1' : '';
  try {
    const result = await api(`/api/wbs/list${includeArchived}`);
    wbsTableBody.replaceChildren(...(result.records || []).map(renderWbsRow));
    setBadge(wbsBadge, 'ok', `${result.count} 条`);
    wbsOutput.textContent = `加载 ${result.count} 条 WBS 记录。`;
  } catch (error) {
    setBadge(wbsBadge, 'bad', '加载失败');
    wbsOutput.textContent = error.stack || error.message;
  }
}

async function wbsMutate(path, payload) {
  try {
    const result = await api(path, payload);
    wbsOutput.textContent = pretty(result);
    await loadWbs();
  } catch (error) {
    wbsOutput.textContent = error.stack || error.message;
  }
}

wbsForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const record = wbsFormData();
  if (!record.wbsCode) { wbsOutput.textContent = 'WBS编码为必填。'; return; }
  await wbsMutate('/api/wbs/upsert', record);
});

document.querySelector('#wbsReset').addEventListener('click', () => {
  wbsForm.reset();
});
document.querySelector('#wbsRefresh').addEventListener('click', loadWbs);
wbsShowArchived.addEventListener('change', loadWbs);

refreshStatus().catch((error) => {
  setBadge(serviceBadge, 'bad', '服务异常');
  statusBox.textContent = error.stack || error.message;
});

loadWbs();
