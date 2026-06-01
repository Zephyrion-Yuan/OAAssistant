import fs from 'node:fs';
import path from 'node:path';
import { ensureDir, runtimeDir } from '../src/config.js';

const pages = ['oa-workflow-458', 'oa-workflow-412', 'oa-workflow-414', 'oa-workflow-89'];

function fieldsFromLoadForm(loadForm) {
  const tableInfo = loadForm?.responseBody?.value?.tableInfo || {};
  const fields = [];
  for (const [tableName, table] of Object.entries(tableInfo)) {
    const fieldMap = table?.fieldinfomap || {};
    for (const field of Object.values(fieldMap)) {
      fields.push({
        table: tableName,
        tableIndex: table.tableindex,
        tableDb: table.tablename,
        fieldId: field.fieldid,
        key: `field${field.fieldid}`,
        label: field.fieldlabel,
        name: field.fieldname,
        isDetail: field.isdetail,
        groupId: field.groupid,
        htmlType: field.htmltype,
        detailType: field.detailtype,
        dbType: field.fielddbtype,
        viewAttr: field.viewattr,
        required: field.viewattr === 3,
        editable: field.viewattr === 2 || field.viewattr === 3,
        onlyShow: field.isonlyshow,
        existLayout: field.existLayout,
        options: field.selectattr?.selectitemlist || []
      });
    }
  }
  return fields;
}

async function postJson(url, body) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

const summary = {};
for (const pageId of pages) {
  const scan = await postJson('http://127.0.0.1:8787/api/oa/scan', { pageId });
  const loadForm = scan.apiCalls.find((call) => call.url.includes('/api/workflow/reqform/loadForm'));
  const fields = fieldsFromLoadForm(loadForm);
  summary[pageId] = {
    pageId,
    title: scan.title,
    url: scan.url,
    requiresLogin: scan.requiresLogin,
    fieldCount: fields.length,
    requiredCount: fields.filter((field) => field.required).length,
    editableCount: fields.filter((field) => field.editable).length,
    requiredFields: fields.filter((field) => field.required),
    editableMain: fields.filter((field) => field.editable && field.isDetail === 0),
    editableDetail: fields.filter((field) => field.editable && field.isDetail === 1),
    buttons: [...new Set(scan.buttons.map((button) => button.text).filter(Boolean))],
    workflowApiUrls: [...new Set(
      scan.apiCalls
        .filter((call) => call.url.includes('/api/workflow'))
        .map((call) => `${call.method} ${call.url.replace(/\?.*$/, '')}`)
    )],
    fields
  };
}

const outputDir = path.join(runtimeDir, 'oa-field-summary');
ensureDir(outputDir);
const outputPath = path.join(outputDir, `summary-${Date.now()}.json`);
const latestPath = path.join(outputDir, 'summary-latest.json');
fs.writeFileSync(outputPath, JSON.stringify(summary, null, 2), 'utf8');
fs.writeFileSync(latestPath, JSON.stringify(summary, null, 2), 'utf8');
console.log(latestPath);
