import fs from 'node:fs';
import path from 'node:path';
import { scanOaPage } from '../src/automation/oaAutomation.js';
import { ensureDir, runtimeDir } from '../src/config.js';

const pageId = process.argv[2] || 'oa-workflow-458';
const result = await scanOaPage({ pageId });
const outputDir = path.join(runtimeDir, 'scan-results');
ensureDir(outputDir);
const outputPath = path.join(outputDir, `${pageId}-${Date.now()}.json`);
fs.writeFileSync(outputPath, JSON.stringify(result, null, 2), 'utf8');
console.log(outputPath);
