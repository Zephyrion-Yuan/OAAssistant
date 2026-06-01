import fs from 'node:fs';
import path from 'node:path';

const summaryPath =
  process.argv[2] ||
  path.join(process.cwd(), '.runtime', 'oa-field-summary', 'summary-latest.json');

const raw = fs.readFileSync(summaryPath, 'utf8');
const summary = JSON.parse(raw);

for (const [pageId, page] of Object.entries(summary)) {
  console.log(`\n## ${pageId} ${page.title}`);
  console.log(
    `fields=${page.fieldCount} required=${page.requiredCount} editable=${page.editableCount} requiresLogin=${page.requiresLogin}`,
  );

  console.log('requiredFields:');
  for (const field of page.requiredFields || []) {
    const parts = [
      `${field.table}.${field.key}`,
      field.label,
      field.name || '',
      `html=${field.htmlType}`,
      `type=${field.detailType}`,
      `db=${field.dbType || ''}`,
    ];
    console.log(`- ${parts.join(' | ')}`);
  }

  const buttons = page.buttons || [];
  console.log(`buttons: ${buttons.length ? buttons.join(' | ') : '(none)'}`);

  const apiPaths =
    page.workflowApiUrls ||
    [
      ...new Set(
        (page.apiCalls || []).map((call) => {
          const url = new URL(call.url);
          return `${call.method} ${url.origin}${url.pathname}`;
        }),
      ),
    ];
  console.log(`apis: ${apiPaths.length ? apiPaths.join(' | ') : '(none)'}`);
}
