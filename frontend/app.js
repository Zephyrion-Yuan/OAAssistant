/* OA 采购助手 — Vue 3 (shell/config) + deep-chat (left conversation pane).
   Pure consumer of the BFF: only fetch/SSE, never imports backend, never hits Node directly. */
const { createApp } = Vue;

function blankDemandRow(values = {}) {
  return Object.assign({ materialCode: '', materialName: '', quantity: '', unit: '', wbsCode: '', demandFactoryCode: '' }, values);
}

function blankWbs() {
  return { wbsCode: '', alias: '', projectDefinition: '', demandFactoryCode: '', costCenter: '',
    purchaser: '', mrpController: '', stockLocationName: '', stockLocationSapCode: '',
    projectType: '', purchaseType: '', purchaseDemandType: '',
    deliveryAddress: '', demandDateOffsetDays: '', remark: '', status: 'active' };
}
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const WF = { '412': ['412 出库', '#2563eb'], '89': ['89 转储', '#be185d'], '458': ['458 采购', '#b45309'], '414': ['414 入库', '#047857'] };
const PURCHASE_HEADER_ALIASES = {
  materialCode: ['物料编码', '物料编号', '物料号', '物料代码'],
  materialName: ['物料名称', '物料描述', '名称', '描述'],
  quantity: ['采购数量', '需求数量', '申请数量', '数量']
};

function normalizeHeader(value) {
  return String(value == null ? '' : value).replace(/\s+/g, '').trim();
}

function normalizeCell(value) {
  if (value == null) return '';
  if (value instanceof Date && !Number.isNaN(value.getTime())) {
    return value.toISOString().slice(0, 10);
  }
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : String(value).replace(/\.0+$/, '');
  }
  return String(value).trim();
}

function normalizeMaterialCode(value) {
  const text = normalizeCell(value).replace(/\s+/g, '');
  return text.replace(/^(\d+)\.0+$/, '$1');
}

function normalizeQuantityText(value) {
  const text = normalizeCell(value).replace(/[,，]/g, '');
  if (!/^[-+]?(?:\d+|\d+\.\d+|\.\d+)$/.test(text)) return '';
  return trimDecimalText(text);
}

function trimDecimalText(value) {
  let text = String(value || '').trim();
  if (!text) return '0';
  const negative = text.startsWith('-');
  if (text[0] === '-' || text[0] === '+') text = text.slice(1);
  if (text.startsWith('.')) text = `0${text}`;
  if (text.includes('.')) text = text.replace(/0+$/, '').replace(/\.$/, '');
  text = text.replace(/^0+(?=\d)/, '') || '0';
  return negative && text !== '0' ? `-${text}` : text;
}

function decimalToScaled(value) {
  const text = trimDecimalText(String(value || '0').replace(/[,，]/g, ''));
  const negative = text.startsWith('-');
  const clean = negative ? text.slice(1) : text;
  const [intPart, fracPart = ''] = clean.split('.');
  return { sign: negative ? -1n : 1n, intPart: intPart || '0', fracPart };
}

function addDecimalText(a, b) {
  const left = decimalToScaled(a);
  const right = decimalToScaled(b);
  const scale = Math.max(left.fracPart.length, right.fracPart.length);
  const factor = 10n ** BigInt(scale);
  const toInt = (item) => {
    const whole = BigInt(item.intPart || '0') * factor;
    const frac = BigInt((item.fracPart || '').padEnd(scale, '0') || '0');
    return item.sign * (whole + frac);
  };
  const sum = toInt(left) + toInt(right);
  const negative = sum < 0n;
  const abs = negative ? -sum : sum;
  const whole = abs / factor;
  const frac = scale ? String(abs % factor).padStart(scale, '0').replace(/0+$/, '') : '';
  return `${negative && abs !== 0n ? '-' : ''}${whole}${frac ? `.${frac}` : ''}`;
}

function isPositiveDecimal(value) {
  return /^(\d+|\d+\.\d+|\.\d+)$/.test(normalizeQuantityText(value)) && Number(normalizeQuantityText(value)) > 0;
}

function findAliasColumn(row, aliases) {
  const normalized = new Set(aliases.map(normalizeHeader));
  return row.findIndex((cell) => normalized.has(normalizeHeader(cell)));
}

function resolvePurchaseColumns(table) {
  const maxHeaderRows = Math.min(table.length, 10);
  for (let rowIndex = 0; rowIndex < maxHeaderRows; rowIndex += 1) {
    const row = table[rowIndex] || [];
    const materialCode = findAliasColumn(row, PURCHASE_HEADER_ALIASES.materialCode);
    const materialName = findAliasColumn(row, PURCHASE_HEADER_ALIASES.materialName);
    const quantity = findAliasColumn(row, PURCHASE_HEADER_ALIASES.quantity);
    if (materialCode >= 0 && quantity >= 0) return { headerRow: rowIndex, materialCode, materialName, quantity };
  }
  throw new Error('Sheet1 未找到“物料编码”和“采购数量/需求数量”表头。');
}

function looksLikeInstructionRow(row) {
  return row.some((cell) => /必填|选填|填写|YYYYMMDD|参照页签|需求类型/.test(normalizeCell(cell)));
}

function extractPurchaseRows(workbook) {
  if (!workbook || !workbook.SheetNames || !workbook.SheetNames.length) {
    throw new Error('工作簿没有 Sheet1。');
  }
  const sheetName = workbook.SheetNames[0];
  const sheet = workbook.Sheets[sheetName];
  const table = XLSX.utils.sheet_to_json(sheet, { header: 1, defval: '', raw: true });
  const columns = resolvePurchaseColumns(table);
  const rows = [];
  const warnings = [];
  for (let rowIndex = columns.headerRow + 1; rowIndex < table.length; rowIndex += 1) {
    const row = table[rowIndex] || [];
    const materialCode = normalizeMaterialCode(row[columns.materialCode]);
    const materialName = columns.materialName >= 0 ? normalizeCell(row[columns.materialName]) : '';
    const quantity = normalizeQuantityText(row[columns.quantity]);
    if (!materialCode && !quantity) continue;
    if (looksLikeInstructionRow(row)) continue;
    if (!materialCode) {
      warnings.push(`第 ${rowIndex + 1} 行缺少物料编码，已跳过。`);
      continue;
    }
    if (!quantity || !isPositiveDecimal(quantity)) {
      warnings.push(`第 ${rowIndex + 1} 行采购数量无效，已跳过。`);
      continue;
    }
    rows.push({ materialCode, materialName, quantity, rowNumber: rowIndex + 1, sheetName });
  }
  if (!rows.length) throw new Error('Sheet1 没有可导入的物料编码和采购数量。');
  return { rows, warnings, sheetName };
}

function isBlankDemandRow(row) {
  return !Object.values(row || {}).some((value) => String(value == null ? '' : value).trim());
}

createApp({
  data() {
    return {
      bff: localStorage.getItem('oaa.bff') || 'http://127.0.0.1:8788',
      userId: 'tester', executor: 'mock', health: { ok: false },
      drawer: false, cfgTab: '初始化', sessionOut: '',
      profile: { user_id: 'tester', department: '', default_factory_code: '', default_movement_type: '',
        default_wbs: '', default_transfer_out_stock_location_name: '', default_transfer_out_stock_location_sap: '',
        default_transfer_in_stock_location_name: '', default_transfer_in_stock_location_sap: '' },
      profileMsg: '',
      wbsList: [], wbsForm: blankWbs(), wbsMsg: '', wbsShowArchived: false, wbsDeleteArm: '',
      optionCatalog: { groups: {} }, optionMsg: '',
      demandRows: [blankDemandRow()],
      uploadState: { busy: false, message: '', files: [], lastRows: [], warnings: [], errors: [] },
      chatMessage: '', save: false, busy: false,
      activeThreadId: '', awaitingInput: false,
    };
  },
  mounted() {
    this.ping();
    const self = this;
    customElements.whenDefined('deep-chat').then(() => {
      const dc = self.$refs.dc;
      if (!dc) return;
      dc.avatars = true;
      dc.textInput = { placeholder: { text: '问采购助手,或在右侧填需求行点「发起申请」' } };
      dc.messageStyles = { default: { ai: { bubble: { backgroundColor: '#f6f8fc', color: '#1b2435' } }, user: { bubble: { backgroundColor: '#2563eb' } } } };
      dc.history = [{ role: 'ai', html: self.intro() }];
      dc.connect = { stream: true, handler: (body, signals) => self.chatHandler(body, signals) };
    });
  },
  methods: {
    persist() { localStorage.setItem('oaa.bff', this.bff); },
    async api(path, method = 'GET', body = null) {
      const opt = { method, headers: { 'Content-Type': 'application/json; charset=utf-8' } };
      if (body !== null) opt.body = JSON.stringify(body);
      const r = await fetch(this.bff + path, opt); const d = await r.json();
      if (!r.ok) throw new Error(d.detail || d.error || r.statusText);
      return d;
    },
    async ping() {
      try { this.health = await this.api('/api/health'); } catch { this.health = { ok: false }; }
      if (this.health.ok) { try { this.sessionOut = JSON.stringify(await this.api('/api/session/status'), null, 2); } catch (e) { this.sessionOut = String(e.message); } }
    },
    // ---- config: init ----
    async call(path, method) { try { this.sessionOut = JSON.stringify(await this.api(path, method, method === 'POST' ? {} : null), null, 2); } catch (e) { this.sessionOut = '错误:' + e.message; } },
    // ---- config: profile ----
    async loadProfile() {
      try { const r = await this.api('/api/profile/' + encodeURIComponent(this.userId));
        if (r.found) { this.profile = Object.assign({ user_id: this.userId }, r.profile); this.profileMsg = '已加载。'; } else this.profileMsg = '暂无画像。'; }
      catch (e) { this.profileMsg = '错误:' + e.message; }
    },
    async saveProfile() { try { this.profile.user_id = this.userId; const r = await this.api('/api/profile', 'POST', this.profile); this.profileMsg = '已保存:' + JSON.stringify(r.profile); } catch (e) { this.profileMsg = '错误:' + e.message; } },
    // ---- config: backend option catalog ----
    async loadOptionCatalog() {
      try {
        this.optionCatalog = await this.api('/api/options/catalog');
        this.optionMsg = '';
        if (!this.wbsForm.projectType && !this.wbsForm.purchaseType && !this.wbsForm.purchaseDemandType) {
          this.wbsForm = Object.assign(blankWbs(), this.wbsDefaults(), this.wbsForm);
        }
      } catch (e) {
        this.optionCatalog = { groups: {} };
        this.optionMsg = '选项目录加载失败:' + e.message;
      }
    },
    optionGroup(key) { return this.optionCatalog.groups?.[key]?.options || []; },
    optionDefault(key) { return this.optionCatalog.groups?.[key]?.defaultValue || ''; },
    wbsDefaults() {
      return {
        projectType: this.optionDefault('oa458.projectType'),
        purchaseType: this.optionDefault('oa458.purchaseType'),
        purchaseDemandType: this.optionDefault('oa458.purchaseDemandType'),
      };
    },
    // ---- config: wbs ----
    async loadWbs() { try { await this.loadOptionCatalog(); const r = await this.api('/api/wbs/list' + (this.wbsShowArchived ? '?includeArchived=true' : '')); this.wbsList = r.records || []; this.wbsMsg = '共 ' + (r.count ?? this.wbsList.length) + ' 条。'; } catch (e) { this.wbsMsg = '错误:' + e.message; } },
    editWbs(w) { this.wbsForm = Object.assign(blankWbs(), this.wbsDefaults(), w); },
    resetWbsForm() { this.wbsForm = Object.assign(blankWbs(), this.wbsDefaults()); },
    async saveWbs() { if (!this.wbsForm.wbsCode) { this.wbsMsg = 'WBS编码必填。'; return; } try { const r = await this.api('/api/wbs/upsert', 'POST', this.wbsForm); this.wbsMsg = (r.created ? '已新增 ' : '已更新 ') + this.wbsForm.wbsCode; await this.loadWbs(); } catch (e) { this.wbsMsg = '错误:' + e.message; } },
    async delWbs(code) {
      if (this.wbsDeleteArm !== code) { this.wbsDeleteArm = code; setTimeout(() => { if (this.wbsDeleteArm === code) this.wbsDeleteArm = ''; }, 3000); return; }
      this.wbsDeleteArm = ''; try { await this.api('/api/wbs/delete', 'POST', { wbsCode: code }); this.wbsMsg = '已删 ' + code; await this.loadWbs(); } catch (e) { this.wbsMsg = '错误:' + e.message; }
    },
    // ---- request builder ----
    addRow() { this.demandRows.push(blankDemandRow({ quantity: '1' })); },
    clearDemandRows() {
      this.demandRows = [blankDemandRow()];
      this.uploadState = { busy: false, message: '已清空采购需求草稿。', files: [], lastRows: [], warnings: [], errors: [] };
    },
    requestRows() {
      return this.demandRows
        .map((row) => ({
          materialCode: normalizeMaterialCode(row.materialCode),
          quantity: normalizeQuantityText(row.quantity) || normalizeCell(row.quantity),
          unit: normalizeCell(row.unit),
          wbsCode: normalizeCell(row.wbsCode),
          demandFactoryCode: normalizeCell(row.demandFactoryCode),
        }))
        .filter((row) => row.materialCode);
    },
    displayRows() {
      return this.demandRows
        .map((row) => ({
          materialCode: normalizeMaterialCode(row.materialCode),
          materialName: normalizeCell(row.materialName),
          quantity: normalizeQuantityText(row.quantity) || normalizeCell(row.quantity),
        }))
        .filter((row) => row.materialCode);
    },
    send() {
      if (this.busy) return;
      const requestRows = this.requestRows();
      if (!requestRows.length) {
        this.uploadState.message = '请先填写物料编码，或上传采购附件导入物料。';
        return;
      }
      const dc = this.$refs.dc;
      const text = this.chatMessage.trim() || ('采购申请(' + requestRows.length + ' 行,' + (this.save ? '保存草稿' : 'dry-run') + ')');
      this.busy = true;
      if (dc && typeof dc.submitUserMessage === 'function') dc.submitUserMessage({ text });
      else this.chatHandler({ messages: [{ text }] }, { onOpen() {}, onResponse() {}, onClose() {} });
    },
    async importPurchaseFiles(event) {
      const files = Array.from(event?.target?.files || []);
      if (event?.target) event.target.value = '';
      if (!files.length) return;
      if (!window.XLSX) {
        this.uploadState.message = 'Excel 解析库未加载，请检查网络后刷新页面。';
        return;
      }

      this.uploadState = { busy: true, message: '正在解析采购附件...', files: [], lastRows: [], warnings: [], errors: [] };
      const imported = [];
      const warnings = [];
      const errors = [];
      for (const file of files) {
        if (!/\.(xlsx|xls)$/i.test(file.name)) {
          errors.push(`${file.name}: 仅支持 .xlsx / .xls 文件。`);
          continue;
        }
        try {
          const workbook = XLSX.read(await file.arrayBuffer(), { type: 'array', cellDates: true });
          const result = extractPurchaseRows(workbook);
          const merged = this.mergePurchaseRows(result.rows);
          imported.push({ fileName: file.name, count: result.rows.length, appended: merged.appended, merged: merged.merged });
          warnings.push(...result.warnings.map((text) => `${file.name}: ${text}`));
        } catch (error) {
          errors.push(`${file.name}: ${error.message}`);
        }
      }
      const total = imported.reduce((sum, item) => sum + item.count, 0);
      const appended = imported.reduce((sum, item) => sum + item.appended, 0);
      const merged = imported.reduce((sum, item) => sum + item.merged, 0);
      this.uploadState = {
        busy: false,
        message: total ? `已导入 ${total} 行，新增 ${appended} 行，累加 ${merged} 行。` : '未导入任何采购需求行。',
        files: imported,
        lastRows: total ? this.displayRows().slice(-total).slice(0, 12) : [],
        warnings,
        errors,
      };
    },
    mergePurchaseRows(rows) {
      if (this.demandRows.length === 1 && isBlankDemandRow(this.demandRows[0])) this.demandRows = [];
      let appended = 0;
      let merged = 0;
      for (const row of rows) {
        const existing = this.demandRows.find((item) => normalizeMaterialCode(item.materialCode) === row.materialCode);
        if (existing) {
          existing.quantity = addDecimalText(normalizeQuantityText(existing.quantity) || '0', row.quantity);
          if (row.materialName && normalizeCell(existing.materialName) !== row.materialName) existing.materialName = row.materialName;
          merged += 1;
        } else {
          this.demandRows.push(blankDemandRow({ materialCode: row.materialCode, materialName: row.materialName, quantity: row.quantity }));
          appended += 1;
        }
      }
      if (!this.demandRows.length) this.demandRows = [blankDemandRow()];
      return { appended, merged };
    },
    // ---- deep-chat streaming handler: BFF SSE -> progress + draft cards (inline-styled html) ----
    async chatHandler(body, signals) {
      this.busy = true;
      signals.onOpen();
      const msg = (body && body.messages && body.messages.length ? body.messages[body.messages.length - 1].text : '') || this.chatMessage;
      const demandRows = this.requestRows();
      if (!demandRows.length) {
        try { signals.onResponse({ html: '<div style="color:#b42318">请先填写物料编码，或上传采购附件导入物料。</div>' }); } catch (_) {}
        signals.onClose(); this.busy = false; return;
      }
      const continuation = Boolean(this.awaitingInput && this.activeThreadId);
      const payload = {
        message: msg,
        demandRows,
        save: this.save,
        executor: this.executor,
        userId: this.userId,
        threadId: continuation ? this.activeThreadId : undefined,
        continueThread: continuation,
      };
      const nodes = [];
      let tail = '';
      const push = () => { try { signals.onResponse({ html: this.progressHtml(nodes) + tail, overwrite: true }); } catch (e) { /* first call may not allow overwrite */ try { signals.onResponse({ html: this.progressHtml(nodes) + tail }); } catch (_) {} } };
      try {
        const resp = await fetch(this.bff + '/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        if (!resp.ok || !resp.body) throw new Error('HTTP ' + resp.status);
        const reader = resp.body.getReader(); const dec = new TextDecoder(); let buf = '';
        while (true) {
          const { done, value } = await reader.read(); if (done) break;
          buf += dec.decode(value, { stream: true }); let idx;
          while ((idx = buf.indexOf('\n\n')) >= 0) {
            const line = buf.slice(0, idx).trim(); buf = buf.slice(idx + 2);
            if (!line.startsWith('data:')) continue;
            const ev = JSON.parse(line.slice(5).trim());
            if (ev.type === 'start') { this.activeThreadId = ev.threadId || this.activeThreadId; }
            else if (ev.type === 'node') { nodes.push(ev.node); push(); }
            else if (ev.type === 'final') { this.awaitingInput = false; this.activeThreadId = ''; tail = this.finalHtml(ev); push(); }
            else if (ev.type === 'needs_input') { this.awaitingInput = true; this.activeThreadId = ev.threadId || this.activeThreadId; tail = this.needsHtml(ev); push(); }
            else if (ev.type === 'error') { tail = `<div style="color:#b42318">⚠ 错误:${esc(ev.error)}</div>`; push(); }
          }
        }
      } catch (e) {
        tail = `<div style="color:#b42318">⚠ ${esc(e.message)}</div>`; push();
      } finally {
        signals.onClose(); this.busy = false;
      }
    },
    // ---- inline-styled HTML (rendered inside deep-chat shadow DOM) ----
    intro() {
      return `<div style="font-size:13px;line-height:1.6">你好 👋 我是 OA 采购助手。<br>在右侧填好<b>需求行</b>(WBS 可写编码或<b>别称</b>),点「发起申请」,我会查 PDM、看库存,实时把它分流成 <b>412 出库 / 89 转储 / 458 采购</b> 草稿(按 WBS 分桶,<b>永不提交</b>)。</div>`;
    },
    progressHtml(nodes) {
      const label = { intake: '读取需求', preflight: '预检', resolve_wbs: '解析WBS别称', classify_goal: '识别意图', pdm_enrich: '校验物料(PDM)', unit_check: '单位校验', inventory_query: '查库存', route_workflow: '分配路由', prepare: '补全+生成附件', execute_plan: '填单(草稿)', finalize: '汇总' };
      if (!nodes.length) return '';
      const chips = nodes.map((n) => `<span style="display:inline-block;background:#eef2fb;color:#3a4a6b;border-radius:999px;padding:2px 9px;margin:2px 4px 2px 0;font-size:11px">${esc(label[n] || n)}</span>`).join('');
      return `<div style="margin-bottom:8px"><div style="font-size:11px;color:#8a93a6;margin-bottom:3px">运行轨迹</div>${chips}</div>`;
    },
    draftCard(d) {
      const [name, color] = WF[d.workflow_id] || [d.workflow_id, '#64748b'];
      const lines = (d.materialLines || []).map((l) => `${esc(l.materialCode)}×${esc(l.quantity)}${esc(l.unit || '')}`).join('  ');
      const src = d.transferOutWbs ? ` <span style="color:#8a93a6">← ${esc(d.transferOutWbs)}</span>` : '';
      const stat = d.ok ? `<span style="color:#157347">✓ ${esc(d.requestId || '已填(dry-run)')}</span>` : (d.skipped ? `<span style="color:#9a6700">跳过:${esc(d.skipReason || '')}</span>` : '待补输入');
      return `<div style="border:1px solid #e1e6ef;border-left:4px solid ${color};border-radius:10px;padding:9px 11px;margin:6px 0;background:#fff">
        <div style="font-weight:600">${esc(name)} · WBS ${esc(d.wbsCode)}${src}</div>
        <div style="color:#6b7488;font-size:12px;margin:3px 0">${lines}</div>
        <div style="font-size:12px">${stat}</div></div>`;
    },
    finalHtml(ev) {
      const head = `<div style="margin:6px 0 2px"><b style="color:${ev.status === 'done' ? '#157347' : '#9a6700'}">${ev.status === 'done' ? '完成' : esc(ev.status)}</b> <span style="color:#8a93a6;font-size:12px">${ev.dryRun ? '· dry-run 未保存' : ''} · 草稿 ${(ev.drafts || []).length} 张</span></div>`;
      const cards = (ev.drafts || []).map((d) => this.draftCard(d)).join('');
      const notes = (ev.notes || []).length ? `<div style="font-size:12px;color:#8a93a6;margin-top:4px">${ev.notes.map((n) => '· ' + esc(n)).join('<br>')}</div>` : '';
      return head + cards + notes;
    },
    needsHtml(ev) {
      const cards = (ev.drafts || []).map((d) => this.draftCard(d)).join('');
      const detail = this.needsDetailHtml(ev.detail || {});
      const mode = ev.resumeMode || (ev.detail && ev.detail.resumeMode) || 'correct';
      const head = mode === 'action' ? '需要操作或补充' : '需补充信息';
      const tip = mode === 'action'
        ? '在 OA / 主数据里处理后回复「已处理 / 已登录」即可继续；也可以直接补充缺失信息。'
        : mode === 'mixed'
        ? '可直接补充缺失信息，或在 OA / 主数据处理后回复「已处理」继续。'
        : '下一条消息会作为本线程的补充 / 修正继续处理，不会重新发起新需求。';
      const tips = `<div style="font-size:12px;color:#6b7488;margin-top:6px">${tip}</div>`;
      return `<div style="border:1px solid #f0d9a8;background:#fff8ea;border-radius:10px;padding:9px 11px;margin:6px 0">
        <b style="color:#9a6700">${head}</b> <span style="color:#8a93a6;font-size:12px">(${esc(ev.kind || '')})</span>
        <div style="margin-top:3px;white-space:pre-wrap">${esc(ev.question || '')}</div>${detail}${tips}</div>${cards}`;
    },
    needsDetailHtml(detail) {
      const items = Array.isArray(detail.items) ? detail.items : [];
      if (detail.kind === 'unitReview' && items.length) {
        const rows = items.map((it) => `<tr>
          <td style="padding:4px 6px;border-top:1px solid #efd8a2">${esc(it.materialCode || '')}</td>
          <td style="padding:4px 6px;border-top:1px solid #efd8a2">${esc(it.demandQuantity || '')} ${esc(it.demandUnit || '')}</td>
          <td style="padding:4px 6px;border-top:1px solid #efd8a2">${esc(it.baseUnit || '')}</td>
          <td style="padding:4px 6px;border-top:1px solid #efd8a2">${esc(it.suggestedQuantity || '-')} ${esc(it.suggestedUnit || '')}</td>
          <td style="padding:4px 6px;border-top:1px solid #efd8a2">${esc(it.reason || '')}</td>
        </tr>`).join('');
        return `<table style="width:100%;border-collapse:collapse;margin-top:8px;font-size:12px">
          <thead><tr style="text-align:left;color:#6b7488"><th>物料</th><th>需求</th><th>PDM单位</th><th>建议</th><th>原因</th></tr></thead>
          <tbody>${rows}</tbody></table>`;
      }
      if (items.length) {
        const lines = items.map((it) => `${esc(it.workflow_id || it.workflow || '')} / WBS ${esc(it.wbsCode || '-')}: ${esc(it.question || it.error || it.kind || '')}`).join('<br>');
        return `<div style="font-size:12px;color:#6b7488;margin-top:8px">${lines}</div>`;
      }
      if (Array.isArray(detail.badCodes) && detail.badCodes.length) {
        return `<div style="font-size:12px;color:#6b7488;margin-top:8px">异常物料: ${detail.badCodes.map(esc).join(', ')}</div>`;
      }
      return '';
    },
  },
}).mount('#app');
