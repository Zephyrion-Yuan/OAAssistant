import { sensitiveNamePattern } from '../security/redaction.js';
import { waitForSettledPage } from '../automation/domScanner.js';

const dangerousButtonPattern = /提交|批准|审批|同意|付款|支付|删除|作废|发布|发送|submit|approve|pay|delete|publish|send/i;

function assertSafeAction(action) {
  const merged = [action.name, action.selector, action.text, action.label].filter(Boolean).join(' ');
  if (['fill', 'select'].includes(action.type) && sensitiveNamePattern.test(merged)) {
    throw new Error(`Refusing to operate on sensitive-looking field: ${action.name || action.selector || action.label}`);
  }
  if (['click', 'clickText'].includes(action.type) && dangerousButtonPattern.test(merged)) {
    throw new Error(`Refusing to click dangerous-looking control: ${action.name || action.selector || action.text}`);
  }
}

async function locatorText(locator) {
  return (await locator.first().innerText({ timeout: 1500 }).catch(() => '')).replace(/\s+/g, ' ').trim();
}

async function assertSafeClick(locator, action) {
  const text = await locatorText(locator);
  const merged = [action.name, action.selector, action.text, text].filter(Boolean).join(' ');
  if (dangerousButtonPattern.test(merged)) {
    throw new Error(`Refusing to click dangerous-looking control: ${text || action.selector || action.text}`);
  }
  return text;
}

function locatorForAction(page, action) {
  if (action.selector) return page.locator(action.selector);
  if (action.text) return page.getByText(action.text, { exact: action.exact !== false });
  throw new Error(`Action ${action.name || action.type} requires selector or text.`);
}

export async function runExplorationActions(page, actions = [], recorder) {
  const results = [];
  for (const [index, action] of actions.entries()) {
    const name = action.name || `${action.type}-${index + 1}`;
    recorder?.setPhase(name);
    const startedCount = recorder?.count() || 0;
    const startedAt = new Date().toISOString();
    try {
      assertSafeAction(action);
      if (action.type === 'fill') {
        const locator = locatorForAction(page, action).first();
        await locator.waitFor({ timeout: action.timeoutMs || 15000 });
        await locator.scrollIntoViewIfNeeded();
        await locator.fill(String(action.value ?? ''));
      } else if (action.type === 'select') {
        const locator = locatorForAction(page, action).first();
        await locator.waitFor({ timeout: action.timeoutMs || 15000 });
        await locator.selectOption(action.value);
      } else if (action.type === 'check' || action.type === 'uncheck') {
        const locator = locatorForAction(page, action).first();
        await locator.waitFor({ timeout: action.timeoutMs || 15000 });
        if (action.type === 'check') await locator.check();
        else await locator.uncheck();
      } else if (action.type === 'press') {
        const locator = action.selector ? page.locator(action.selector).first() : page.locator('body');
        await locator.press(action.key || 'Enter');
      } else if (action.type === 'click' || action.type === 'clickText') {
        const locator = locatorForAction(page, action).first();
        await locator.waitFor({ timeout: action.timeoutMs || 15000 });
        await assertSafeClick(locator, action);
        await locator.scrollIntoViewIfNeeded();
        await locator.click();
      } else if (action.type === 'waitForSelector') {
        if (!action.selector) throw new Error('waitForSelector requires selector.');
        await page.locator(action.selector).first().waitFor({ timeout: action.timeoutMs || 30000 });
      } else if (action.type === 'wait') {
        await page.waitForTimeout(Number(action.ms || 1000));
      } else if (action.type === 'waitForNetworkIdle') {
        await page.waitForLoadState('networkidle', { timeout: action.timeoutMs || 30000 }).catch(() => {});
      } else {
        throw new Error(`Unsupported exploration action type: ${action.type}`);
      }
      await waitForSettledPage(page);
      results.push({
        name,
        type: action.type,
        ok: true,
        startedAt,
        finishedAt: new Date().toISOString(),
        newApiCallCount: (recorder?.count() || 0) - startedCount
      });
    } catch (error) {
      results.push({
        name,
        type: action.type,
        ok: false,
        error: error.message,
        startedAt,
        finishedAt: new Date().toISOString(),
        newApiCallCount: (recorder?.count() || 0) - startedCount
      });
      if (action.continueOnError !== true) break;
    }
  }
  recorder?.setPhase('post-actions');
  return results;
}
