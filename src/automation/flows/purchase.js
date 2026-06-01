import fs from 'node:fs';
import path from 'node:path';
import { edgeSession } from '../../browser/edgeSession.js';
import { resolveOaPage, runtimeDir, ensureDir } from '../../config.js';
import { waitForSettledPage, detectLoginPage } from '../domScanner.js';
import { attachSafeNetworkRecorder } from '../../explorer/safeNetworkRecorder.js';
import { scanPageSurface } from '../../explorer/surfaceScanner.js';
import { redactUrl } from '../../security/redaction.js';

// Server-callable core of OA workflow 458 (purchase request / 采购申请).
// Excel parsing + attachment normalization has been lifted out: this module
// consumes already-structured `input.structured` (the shape produced by
// scripts/purchase_excel.py or the Python orchestrator intake node), where
// `structured.normalizedPath` points at the normalized attachment to upload.
// The browser lifecycle is owned by the caller (server keeps edgeSession alive;
// the CLI wrapper closes it in finally).

const purchaseRuntimeDir = path.join(runtimeDir, 'purchase-requests');

export class NeedInputError extends Error {
  constructor(message, payload = {}) {
    super(message);
    this.name = 'NeedInputError';
    this.payload = payload;
  }
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

async function clickExactText(page, text, options = {}) {
  const pattern = new RegExp(`^\\s*${escapeRegExp(text)}\\s*$`);
  const locator = page.getByText(pattern).last();
  await locator.waitFor({ timeout: options.timeoutMs || 15000 });
  await locator.scrollIntoViewIfNeeded().catch(() => {});
  await locator.click();
}

async function selectDropdownOption(page, comboboxSelector, optionText) {
  await page.locator(comboboxSelector).first().click();
  await page.waitForTimeout(300);
  await clickExactText(page, optionText);
  await waitForSettledPage(page);
}

async function openBrowserField(page, buttonSelector) {
  await page.locator(buttonSelector).first().waitFor({ timeout: 15000 });
  await page.locator(buttonSelector).first().scrollIntoViewIfNeeded();
  await page.locator(buttonSelector).first().click();
  await page.locator('.ant-modal:visible, [role="dialog"]:visible').last().waitFor({ timeout: 15000 });
  await page.waitForTimeout(500);
}

async function clickSearchInModal(page, responseMatcher = null) {
  const modal = page.locator('.ant-modal:visible, [role="dialog"]:visible').last();
  const responsePromise = responseMatcher
    ? page.waitForResponse(responseMatcher, { timeout: 15000 }).catch(() => null)
    : null;

  await modal.getByRole('button', { name: /^\s*搜\s*索\s*$/ }).first().click();

  if (!responsePromise) {
    await waitForSettledPage(page);
    return null;
  }

  const response = await responsePromise;
  if (!response) return null;
  return response.json().catch(() => null);
}

function browserDataMatcher({ contains }) {
  return (response) => (
    response.status() === 200
    && response.url().includes('/api/public/browser/data/')
    && (!contains || response.url().includes(contains))
  );
}

async function clickVisibleModalResult(page, modal, expectedText, timeoutMs = 3000) {
  const candidates = [
    modal.locator(`[title="${expectedText}"]`).first(),
    modal.locator('tr', { hasText: expectedText }).first(),
    modal.getByText(expectedText, { exact: true }).first()
  ];

  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    for (const candidate of candidates) {
      if (await candidate.isVisible().catch(() => false)) {
        await candidate.scrollIntoViewIfNeeded().catch(() => {});
        await candidate.click();
        return true;
      }
    }
    await page.waitForTimeout(100);
  }
  return false;
}

async function clickFirstModalDataRow(page, modal) {
  const rows = modal.locator('.ant-table-tbody tr, tbody tr').filter({ hasNotText: /^\s*(?:No Data|暂无数据)\s*$/ });
  const firstRow = rows.first();
  if (await firstRow.isVisible().catch(() => false)) {
    await firstRow.click();
    return true;
  }

  const tableBody = modal.locator('.ant-table-body:visible, .ant-table-content:visible, .ant-table:visible').last();
  const box = await tableBody.boundingBox().catch(() => null);
  if (box) {
    await page.mouse.click(box.x + Math.min(90, box.width / 3), box.y + Math.min(42, box.height / 3));
    return true;
  }

  const modalBox = await modal.boundingBox().catch(() => null);
  if (!modalBox) return false;
  await page.mouse.click(modalBox.x + 90, modalBox.y + 205);
  return true;
}

async function selectWbs(page, wbsCode) {
  await openBrowserField(page, '#field21089span > div:nth-of-type(2) > button');
  await page.locator('#POSID:visible').last().fill(wbsCode);
  const modal = page.locator('.ant-modal:visible, [role="dialog"]:visible').last();
  const resultData = await clickSearchInModal(page, browserDataMatcher({ contains: `POSID=${encodeURIComponent(wbsCode)}` }));
  const resultCount = Number(resultData?.total ?? resultData?.count ?? resultData?.data?.total ?? 0);
  if (resultData && resultCount < 1) {
    throw new NeedInputError(`WBS query returned no rows for ${wbsCode}.`, {
      kind: 'wbs',
      question: 'WBS 查询没有返回候选，请确认 WBS 编码。',
      wbsCode
    });
  }

  const clickedExact = await clickVisibleModalResult(page, modal, wbsCode, 800);
  if (!clickedExact) {
    const clickedFirstRow = await clickFirstModalDataRow(page, modal);
    if (!clickedFirstRow) throw new Error(`Could not click WBS result row for ${wbsCode}.`);
  }

  const selectorClosed = await modal.waitFor({ state: 'hidden', timeout: 8000 }).then(() => true).catch(() => false);
  if (!selectorClosed) throw new Error(`WBS result click did not close selector for ${wbsCode}.`);
  await waitForSettledPage(page);
}

async function selectDemandCompany(page, factoryCode, companyName) {
  await openBrowserField(page, '#field10450span > div:nth-of-type(2) > button');
  const modal = page.locator('.ant-modal:visible, [role="dialog"]:visible').last();
  let row = modal.locator('tr', { hasText: factoryCode }).first();
  if (await row.count().catch(() => 0)) {
    await row.waitFor({ timeout: 5000 }).catch(() => {});
  }
  if (!(await row.isVisible().catch(() => false))) {
    const input = page.locator('.ant-modal:visible input.ant-input:visible').first();
    if (await input.count()) {
      await input.fill(factoryCode);
      await clickSearchInModal(page);
    }
    row = modal.locator('tr', { hasText: factoryCode }).first();
  }
  await row.waitFor({ timeout: 15000 });
  if (companyName) {
    const rowText = await row.innerText().catch(() => '');
    if (!rowText.includes(companyName)) {
      throw new Error(`Factory code ${factoryCode} did not match expected company "${companyName}". Row text: ${rowText}`);
    }
  }
  await row.click();
  await waitForSettledPage(page);
}

async function uploadAttachment(page, filePath) {
  if (!fs.existsSync(filePath)) throw new Error(`Attachment does not exist: ${filePath}`);
  const uploadButton = page.getByRole('button', { name: /上传附件/ }).first();
  await uploadButton.waitFor({ timeout: 15000 });
  const fileChooserPromise = page.waitForEvent('filechooser', { timeout: 8000 }).catch(() => null);
  await uploadButton.click();
  const fileChooser = await fileChooserPromise;
  if (fileChooser) {
    await fileChooser.setFiles(filePath);
  } else {
    const input = page.locator('input[type="file"]').last();
    await input.setInputFiles(filePath);
  }
  await waitForSettledPage(page);
  await page.waitForTimeout(1500);
}

async function clickSave(page) {
  const saveButton = page.getByRole('button', { name: /保\s*存/ }).first();
  await saveButton.waitFor({ timeout: 15000 });
  await saveButton.scrollIntoViewIfNeeded();
  await saveButton.click();
  await waitForSettledPage(page);
  await page.waitForTimeout(3000);
}

function stableRequestUrl(requestId) {
  if (!requestId) return null;
  return `https://oa.megarobo.info/spa/workflow/static4form/index.html#/main/workflow/req?requestid=${encodeURIComponent(requestId)}`;
}

async function waitForLoginRecovery(page, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await waitForSettledPage(page).catch(() => {});
    const login = await detectLoginPage(page);
    if (!login.requiresLogin) return false;
    await page.waitForTimeout(2000);
  }
  return true;
}

async function writeFailureArtifact(page, recorder, error) {
  try {
    ensureDir(purchaseRuntimeDir);
    const targetPage = page && !page.isClosed()
      ? page
      : edgeSession.context?.pages?.().find((item) => !item.isClosed() && item.url() !== 'about:blank');
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    const base = {
      ok: false,
      capturedAt: new Date().toISOString(),
      error: error.message,
      needsInput: error instanceof NeedInputError,
      input: error instanceof NeedInputError ? error.payload : null,
      apiCalls: recorder?.calls || []
    };
    if (!targetPage) {
      const failurePath = path.join(purchaseRuntimeDir, `${stamp}-failure.json`);
      fs.writeFileSync(failurePath, JSON.stringify(base, null, 2), 'utf8');
      return { failurePath };
    }
    const screenshotPath = path.join(purchaseRuntimeDir, `${stamp}-failure.png`);
    const surfacePath = path.join(purchaseRuntimeDir, `${stamp}-failure-surface.json`);
    await targetPage.screenshot({ path: screenshotPath, fullPage: true }).catch(() => {});
    const surface = await scanPageSurface(targetPage).catch(() => null);
    fs.writeFileSync(surfacePath, JSON.stringify({
      ...base,
      url: redactUrl(targetPage.url()),
      surface
    }, null, 2), 'utf8');
    return { screenshotPath, surfacePath };
  } catch {
    return null;
  }
}

/**
 * Fill OA workflow 458 (purchase request / 采购申请) from already-structured input.
 *
 * input = {
 *   structured: { projectDefinition, wbsCode, demandFactoryCode, demandCompanyName,
 *                 targetDemandDate, normalizedPath },
 *   url?, purchaseType?, projectType?, loginTimeoutMs?, save: boolean
 * }
 *
 * `structured.normalizedPath` must point at an existing normalized attachment
 * file (the *_excel.py helper writes it; the orchestrator intake node does the
 * same). Throws NeedInputError (missing slot) or Error (failure); the thrown
 * error carries `.artifact`. Returns a structured report on success. Never
 * clicks 提交 — at most saves a draft.
 */
export async function runPurchase(input = {}) {
  let page = null;
  let recorder = null;
  try {
    const excel = input.structured;
    if (!excel || !excel.normalizedPath) {
      throw new Error('runPurchase requires input.structured with a normalizedPath attachment.');
    }

    const purchaseType = input.purchaseType || '项目物资采购申请';
    const projectType = input.projectType || '是';
    const loginTimeoutMs = input.loginTimeoutMs ?? 180000;
    const save = Boolean(input.save);

    const pageConfig = resolveOaPage({ pageId: 'oa-workflow-458', url: input.url });
    page = await edgeSession.newPage();
    recorder = attachSafeNetworkRecorder(page);
    const actions = [];

    await page.goto(pageConfig.url, { waitUntil: 'domcontentloaded' });
    await waitForSettledPage(page);
    let login = await detectLoginPage(page);
    if (login.requiresLogin && loginTimeoutMs > 0) {
      const stillRequiresLogin = await waitForLoginRecovery(page, loginTimeoutMs);
      login = await detectLoginPage(page);
      if (stillRequiresLogin || login.requiresLogin) {
        throw new Error('OA page still requires login after waiting for manual login.');
      }
    } else if (login.requiresLogin) {
      throw new Error('OA page requires login. Complete manual login in the managed Edge profile first.');
    }

    async function step(name, fn) {
      recorder.setPhase(name);
      const startedCount = recorder.count();
      const startedAt = new Date().toISOString();
      try {
        await fn();
        actions.push({
          name,
          ok: true,
          startedAt,
          finishedAt: new Date().toISOString(),
          newApiCallCount: recorder.count() - startedCount
        });
      } catch (error) {
        actions.push({
          name,
          ok: false,
          error: error.message,
          startedAt,
          finishedAt: new Date().toISOString(),
          newApiCallCount: recorder.count() - startedCount
        });
        throw error;
      }
    }

    await step(`Set 是否为项目型 = ${projectType}`, async () => {
      await selectDropdownOption(page, '#weaSelect_1 div[role="combobox"]', projectType);
    });
    await step(`Set 采购类型 = ${purchaseType}`, async () => {
      await selectDropdownOption(page, '#weaSelect_2 div[role="combobox"]', purchaseType);
    });
    await step(`Select WBS ${excel.wbsCode}`, async () => {
      await selectWbs(page, excel.wbsCode);
    });
    await step(`Select 需求公司 ${excel.demandFactoryCode}`, async () => {
      await selectDemandCompany(page, excel.demandFactoryCode, excel.demandCompanyName);
    });
    await step('Upload normalized Excel attachment', async () => {
      await uploadAttachment(page, excel.normalizedPath);
    });
    if (save) {
      await step('Click 保存', async () => {
        await clickSave(page);
      });
    }

    recorder.setPhase('post-save-scan');
    const finalSurface = await scanPageSurface(page);
    const requestId = new URL(page.url()).searchParams.get('requestid')
      || page.url().match(/[?&]requestid=(\d+)/)?.[1]
      || null;
    const requestUrl = stableRequestUrl(requestId);
    const report = {
      ok: true,
      ranAt: new Date().toISOString(),
      page: {
        id: pageConfig.id,
        url: redactUrl(pageConfig.url),
        finalUrl: redactUrl(page.url()),
        requestId,
        requestUrl
      },
      excel,
      parameters: {
        projectType,
        purchaseType,
        save
      },
      actions,
      finalSurface,
      apiCalls: recorder.calls
    };

    ensureDir(purchaseRuntimeDir);
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    const reportPath = path.join(purchaseRuntimeDir, `${stamp}-oa-purchase-from-excel.json`);
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), 'utf8');
    return {
      ok: true,
      reportPath,
      requestId,
      requestUrl,
      normalizedAttachment: excel.normalizedPath,
      summary: {
        projectDefinition: excel.projectDefinition,
        wbsCode: excel.wbsCode,
        demandFactoryCode: excel.demandFactoryCode,
        demandCompanyName: excel.demandCompanyName,
        targetDemandDate: excel.targetDemandDate,
        purchaseType,
        projectType,
        saved: save,
        actionCount: actions.length
      },
      actions
    };
  } catch (error) {
    error.artifact = await writeFailureArtifact(page, recorder, error).catch(() => null);
    throw error;
  }
}
