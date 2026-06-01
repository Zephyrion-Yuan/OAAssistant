import fs from 'node:fs';
import path from 'node:path';
import { publicRuntimePath, runtimeDir } from '../config.js';

const explorationDir = path.join(runtimeDir, 'exploration');

function ensureExplorationDir() {
  fs.mkdirSync(explorationDir, { recursive: true });
}

function slugify(value) {
  return String(value || 'page')
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80) || 'page';
}

function hostSlug(rawUrl) {
  try {
    return slugify(new URL(rawUrl).hostname);
  } catch {
    return 'page';
  }
}

function markdownTable(headers, rows) {
  const escapeCell = (value) => String(value ?? '').replaceAll('|', '\\|').replace(/\s+/g, ' ').trim();
  const header = `| ${headers.map(escapeCell).join(' | ')} |`;
  const divider = `| ${headers.map(() => '---').join(' | ')} |`;
  const body = rows.map((row) => `| ${row.map(escapeCell).join(' | ')} |`);
  return [header, divider, ...body].join('\n');
}

function buildFieldsSection(surface) {
  const rows = (surface.fields || []).map((field) => [
    field.index,
    field.label,
    field.kind,
    field.required ? 'yes' : 'no',
    field.readonly ? 'yes' : 'no',
    field.disabled ? 'yes' : 'no',
    field.lookupCandidate ? 'yes' : 'no',
    field.selector
  ]);
  return rows.length
    ? markdownTable(['#', 'label', 'kind', 'required', 'readonly', 'disabled', 'lookup', 'selector'], rows)
    : 'No visible input fields detected.';
}

function buildButtonsSection(surface) {
  const rows = (surface.buttons || []).map((button) => [
    button.index,
    button.text,
    button.intent,
    button.disabled ? 'yes' : 'no',
    button.selector
  ]);
  return rows.length
    ? markdownTable(['#', 'text', 'intent', 'disabled', 'selector'], rows)
    : 'No visible buttons detected.';
}

function buildTablesSection(surface) {
  const rows = (surface.tables || []).map((table) => [
    table.index,
    table.headers?.join(', '),
    table.rowCount,
    table.selector
  ]);
  return rows.length
    ? markdownTable(['#', 'headers', 'rows', 'selector'], rows)
    : 'No visible tables detected.';
}

function buildApiSection(apiCalls) {
  const rows = (apiCalls || []).map((call) => [
    call.id,
    call.phase,
    call.method,
    call.status ?? '',
    call.classification?.dataQueryCandidate ? 'yes' : 'no',
    call.responseBody?.listCandidates?.map((item) => `${item.path}(${item.length})`).join(', ') || '',
    call.redactedUrl
  ]);
  return rows.length
    ? markdownTable(['#', 'phase', 'method', 'status', 'list API', 'list paths', 'url'], rows)
    : 'No XHR/fetch API calls detected.';
}

function buildDeltasSection(fieldDeltas) {
  const rows = (fieldDeltas || []).map((delta) => [delta.label, delta.before, delta.after, delta.selector]);
  return rows.length
    ? markdownTable(['label', 'before', 'after', 'selector'], rows)
    : 'No field value changes detected after configured interactions.';
}

export function buildExplorationMarkdown(report) {
  const lines = [
    `# Page Exploration - ${report.name}`,
    '',
    `- Explored at: ${report.exploredAt}`,
    `- Target URL: ${report.targetUrl}`,
    `- Final URL: ${report.finalUrl}`,
    `- Title: ${report.finalSurface?.title || report.initialSurface?.title || ''}`,
    `- Requires login: ${report.requiresLogin ? 'yes' : 'no'}`,
    '',
    '## Purpose',
    '',
    'This document records deterministic page knowledge for later agents and scripts. It lists fields, buttons, tables, wrapped APIs, and the effects of configured safe interactions. It must not be used to submit, approve, pay, delete, publish, or send forms automatically.',
    '',
    '## Input Fields',
    '',
    buildFieldsSection(report.finalSurface || report.initialSurface),
    '',
    '## Interactive Buttons',
    '',
    buildButtonsSection(report.finalSurface || report.initialSurface),
    '',
    '## Tables And Result Lists',
    '',
    buildTablesSection(report.finalSurface || report.initialSurface),
    '',
    '## Wrapped APIs',
    '',
    buildApiSection(report.apiCalls),
    '',
    '## Configured Interaction Results',
    '',
    markdownTable(
      ['name', 'type', 'ok', 'new API calls', 'error'],
      (report.actions || []).map((action) => [
        action.name,
        action.type,
        action.ok ? 'yes' : 'no',
        action.newApiCallCount,
        action.error || ''
      ])
    ),
    '',
    '## Field Changes After Interactions',
    '',
    buildDeltasSection(report.fieldDeltas),
    '',
    '## Usage Notes For Later Agents',
    '',
    '- Use the selectors recorded here as candidates, then re-scan before filling because OA/PDM pages can render dynamic component trees.',
    '- For lookup fields, trigger only the documented search/select interactions and verify the resulting field deltas.',
    '- Treat list-like API calls as session-bound browser APIs unless a later deterministic module proves a safe direct API contract.',
    '- Never auto-submit. Show a review-required state and leave final submission to the user.',
    ''
  ];
  return lines.join('\n');
}

export function writeExplorationArtifacts(report) {
  ensureExplorationDir();
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const artifactId = `${stamp}-${slugify(report.name)}-${hostSlug(report.targetUrl)}`;
  const jsonPath = path.join(explorationDir, `${artifactId}.json`);
  const markdownPath = path.join(explorationDir, `${artifactId}.md`);
  fs.writeFileSync(jsonPath, JSON.stringify(report, null, 2), 'utf8');
  fs.writeFileSync(markdownPath, buildExplorationMarkdown(report), 'utf8');
  return {
    artifactId,
    jsonPath,
    markdownPath,
    jsonUrl: publicRuntimePath(jsonPath),
    markdownUrl: publicRuntimePath(markdownPath)
  };
}
