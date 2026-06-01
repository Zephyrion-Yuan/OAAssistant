import fs from 'node:fs';
import { edgeSession } from '../browser/edgeSession.js';
import { resolveOaPage, resolvePdmPage } from '../config.js';
import { redactUrl } from '../security/redaction.js';
import { attachApiRecorder } from './apiRecorder.js';
import { detectLoginPage, scanDom, waitForSettledPage } from './domScanner.js';

const defaultDraftButtonTexts = ['保存草稿', '暂存', '保存'];

function normalize(value) {
  return String(value || '').replace(/\s+/g, '').toLowerCase();
}

function fieldScore(field, key) {
  const target = normalize(key);
  const candidates = [field.label, field.name, field.placeholder, field.id, field.selector].map(normalize);
  if (candidates.some((item) => item === target)) return 100;
  if (candidates.some((item) => item.includes(target) || target.includes(item))) return 50;
  return 0;
}

function chooseField(fields, key) {
  return fields
    .map((field) => ({ field, score: fieldScore(field, key) }))
    .filter((item) => item.score > 0 && !item.field.disabled && !item.field.readonly)
    .sort((a, b) => b.score - a.score)[0]?.field || null;
}

async function setFieldValue(page, field, value) {
  const locator = page.locator(field.selector).first();
  await locator.scrollIntoViewIfNeeded();
  if (field.type === 'file' || field.tag === 'input' && field.type === 'file') {
    await locator.setInputFiles(Array.isArray(value) ? value : [value]);
    return;
  }
  if (field.tag === 'select') {
    await locator.selectOption(String(value)).catch(async () => {
      await locator.selectOption({ label: String(value) });
    });
    return;
  }
  if (field.type === 'combobox' || field.tag !== 'input' && field.tag !== 'textarea') {
    await locator.click();
    await page.keyboard.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A');
    await page.keyboard.type(String(value));
    await page.keyboard.press('Enter').catch(() => {});
    await page.waitForTimeout(300);
    return;
  }
  await locator.evaluate((element, nextValue) => {
    const proto = element.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
    descriptor?.set?.call(element, String(nextValue));
    element.dispatchEvent(new Event('input', { bubbles: true }));
    element.dispatchEvent(new Event('change', { bubbles: true }));
    element.dispatchEvent(new Event('blur', { bubbles: true }));
  }, value);
}

async function uploadAttachments(page, fields, attachments = []) {
  const uploaded = [];
  for (const attachment of attachments) {
    if (!attachment?.path) continue;
    if (!fs.existsSync(attachment.path)) {
      throw new Error(`Attachment does not exist: ${attachment.path}`);
    }
    const fileFields = fields.filter((field) => field.type === 'file' || field.tag === 'input' && field.type === 'file');
    const target = attachment.label
      ? chooseField(fileFields, attachment.label) || fileFields[0]
      : fileFields[0];
    if (!target) {
      throw new Error(`No file input found for attachment: ${attachment.path}`);
    }
    await page.locator(target.selector).first().setInputFiles(attachment.path);
    uploaded.push({ label: target.label, path: attachment.path });
  }
  return uploaded;
}

async function clickDraftButton(page, scan, buttonTexts = defaultDraftButtonTexts) {
  const candidates = scan.buttons.filter((button) => {
    const text = normalize(button.text);
    if (!text || button.disabled) return false;
    if (/提交|submit|发送/.test(text)) return false;
    return buttonTexts.some((candidate) => text.includes(normalize(candidate)));
  });
  if (!candidates.length) {
    return { clicked: false, reason: 'No draft/save button matched', buttonTexts };
  }
  await page.locator(candidates[0].selector).first().scrollIntoViewIfNeeded();
  await page.locator(candidates[0].selector).first().click();
  await page.waitForTimeout(1500);
  return { clicked: true, button: candidates[0] };
}

export async function scanOaPage(input) {
  const pageConfig = resolveOaPage(input);
  const page = await edgeSession.newPage();
  const apiCalls = attachApiRecorder(page);
  await page.goto(pageConfig.url, { waitUntil: 'domcontentloaded' });
  await waitForSettledPage(page);
  const login = await detectLoginPage(page);
  let loginScreenshot = null;
  if (login.requiresLogin) {
    loginScreenshot = await edgeSession.captureLoginScreenshot(page, `oa-${pageConfig.id}-login`);
  }
  const dom = await scanDom(page);
  return {
    page: pageConfig,
    requiresLogin: login.requiresLogin,
    login,
    screenshotUrl: loginScreenshot?.url || null,
    ...dom,
    apiCalls
  };
}

export async function openLoginPage(input) {
  const pageConfig = input.system === 'pdm' ? resolvePdmPage() : resolveOaPage(input);
  const url = input.url || pageConfig?.url || input.targetUrl;
  if (!url) throw new Error('Missing target url');
  const page = await edgeSession.newPage();
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await waitForSettledPage(page);
  const login = await detectLoginPage(page);
  const screenshot = login.requiresLogin ? await edgeSession.captureLoginScreenshot(page, 'manual-login') : null;
  return { login, screenshotUrl: screenshot?.url || null, url: redactUrl(page.url()) };
}

export async function fillOaPage(input) {
  const pageConfig = resolveOaPage(input);
  const page = await edgeSession.newPage();
  const apiCalls = attachApiRecorder(page);
  await page.goto(pageConfig.url, { waitUntil: 'domcontentloaded' });
  await waitForSettledPage(page);

  const login = await detectLoginPage(page);
  if (login.requiresLogin) {
    const screenshot = await edgeSession.captureLoginScreenshot(page, `oa-${pageConfig.id}-login`);
    return {
      page: pageConfig,
      requiresLogin: true,
      login,
      screenshotUrl: screenshot.url,
      filled: [],
      uploaded: []
    };
  }

  let scan = await scanDom(page);
  const filled = [];
  const failed = [];
  for (const [key, value] of Object.entries(input.values || {})) {
    const field = chooseField(scan.fields, key);
    if (!field) {
      failed.push({ key, reason: 'No matching editable field' });
      continue;
    }
    try {
      await setFieldValue(page, field, value);
      filled.push({ key, label: field.label, selector: field.selector, value });
    } catch (error) {
      failed.push({ key, label: field.label, selector: field.selector, reason: error.message });
    }
  }

  await page.waitForTimeout(800);
  scan = await scanDom(page);
  const uploaded = await uploadAttachments(page, scan.fields, input.attachments || []);
  const draft = input.saveDraft ? await clickDraftButton(page, scan, input.draftButtonTexts) : { clicked: false };
  const finalScan = await scanDom(page);
  return {
    page: pageConfig,
    requiresLogin: false,
    filled,
    failed,
    uploaded,
    draft,
    currentUrl: redactUrl(page.url()),
    fieldsAfterFill: finalScan.fields,
    apiCalls
  };
}
