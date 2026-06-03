/* OA 采购助手 — Vue 3 (shell/config) + deep-chat (left conversation pane).
   Pure consumer of the BFF: only fetch/SSE, never imports backend, never hits Node directly. */
const { createApp } = Vue;

function blankWbs() {
  return { wbsCode: '', alias: '', projectDefinition: '', demandFactoryCode: '', costCenter: '',
    purchaser: '', mrpController: '', stockLocationName: '', stockLocationSapCode: '',
    deliveryAddress: '', demandDateOffsetDays: '', remark: '', status: 'active' };
}
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const WF = { '412': ['412 出库', '#2563eb'], '89': ['89 转储', '#be185d'], '458': ['458 采购', '#b45309'], '414': ['414 入库', '#047857'] };

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
      demandRows: [
        { materialCode: '4000023659', materialName: 'PCR板', quantity: '10', unit: 'EA', wbsCode: '传感器项目', demandFactoryCode: '1010' },
        { materialCode: '4000059295', materialName: '传感器', quantity: '5', unit: 'EA', wbsCode: '传感器项目', demandFactoryCode: '1010' },
      ],
      chatMessage: '', save: false, busy: false,
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
    // ---- config: wbs ----
    async loadWbs() { try { const r = await this.api('/api/wbs/list' + (this.wbsShowArchived ? '?includeArchived=true' : '')); this.wbsList = r.records || []; this.wbsMsg = '共 ' + (r.count ?? this.wbsList.length) + ' 条。'; } catch (e) { this.wbsMsg = '错误:' + e.message; } },
    editWbs(w) { this.wbsForm = Object.assign(blankWbs(), w); },
    resetWbsForm() { this.wbsForm = blankWbs(); },
    async saveWbs() { if (!this.wbsForm.wbsCode) { this.wbsMsg = 'WBS编码必填。'; return; } try { const r = await this.api('/api/wbs/upsert', 'POST', this.wbsForm); this.wbsMsg = (r.created ? '已新增 ' : '已更新 ') + this.wbsForm.wbsCode; await this.loadWbs(); } catch (e) { this.wbsMsg = '错误:' + e.message; } },
    async delWbs(code) {
      if (this.wbsDeleteArm !== code) { this.wbsDeleteArm = code; setTimeout(() => { if (this.wbsDeleteArm === code) this.wbsDeleteArm = ''; }, 3000); return; }
      this.wbsDeleteArm = ''; try { await this.api('/api/wbs/delete', 'POST', { wbsCode: code }); this.wbsMsg = '已删 ' + code; await this.loadWbs(); } catch (e) { this.wbsMsg = '错误:' + e.message; }
    },
    // ---- request builder ----
    addRow() { this.demandRows.push({ materialCode: '', materialName: '', quantity: '1', unit: 'EA', wbsCode: '', demandFactoryCode: '' }); },
    send() {
      if (this.busy) return;
      const dc = this.$refs.dc;
      const text = this.chatMessage.trim() || ('采购申请(' + this.demandRows.length + ' 行,' + (this.save ? '保存草稿' : 'dry-run') + ')');
      this.busy = true;
      if (dc && typeof dc.submitUserMessage === 'function') dc.submitUserMessage({ text });
      else this.chatHandler({ messages: [{ text }] }, { onOpen() {}, onResponse() {}, onClose() {} });
    },
    // ---- deep-chat streaming handler: BFF SSE -> progress + draft cards (inline-styled html) ----
    async chatHandler(body, signals) {
      this.busy = true;
      signals.onOpen();
      const msg = (body && body.messages && body.messages.length ? body.messages[body.messages.length - 1].text : '') || this.chatMessage;
      const payload = { message: msg, demandRows: this.demandRows, save: this.save, executor: this.executor, userId: this.userId };
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
            if (ev.type === 'node') { nodes.push(ev.node); push(); }
            else if (ev.type === 'final') { tail = this.finalHtml(ev); push(); }
            else if (ev.type === 'needs_input') { tail = this.needsHtml(ev); push(); }
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
      return `<div style="border:1px solid #f0d9a8;background:#fff8ea;border-radius:10px;padding:9px 11px;margin:6px 0">
        <b style="color:#9a6700">需补充信息</b> <span style="color:#8a93a6;font-size:12px">(${esc(ev.kind || '')})</span>
        <div style="margin-top:3px">${esc(ev.question || '')}</div></div>${cards}`;
    },
  },
}).mount('#app');
