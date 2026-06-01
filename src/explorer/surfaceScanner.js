import { redactUrl } from '../security/redaction.js';

export async function scanPageSurface(page) {
  const surface = await page.evaluate(() => {
    const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim();
    const isVisible = (element) => {
      if (!element) return false;
      const style = window.getComputedStyle(element);
      if (style.visibility === 'hidden' || style.display === 'none' || Number(style.opacity) === 0) return false;
      const rect = element.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    };
    const cssPath = (element) => {
      if (!element || element.nodeType !== Node.ELEMENT_NODE) return '';
      const parts = [];
      let current = element;
      while (current && current.nodeType === Node.ELEMENT_NODE && current !== document.body) {
        let part = current.nodeName.toLowerCase();
        if (current.id && !/[:.[\]\s]/.test(current.id)) {
          parts.unshift(`#${current.id}`);
          break;
        }
        const dataRowKey = current.getAttribute('data-row-key');
        const name = current.getAttribute('name');
        const role = current.getAttribute('role');
        if (name && !/[:.[\]\s]/.test(name)) {
          part += `[name="${name}"]`;
        } else if (dataRowKey && !/[:.[\]\s]/.test(dataRowKey)) {
          part += `[data-row-key="${dataRowKey}"]`;
        } else if (role && ['button', 'combobox', 'textbox', 'gridcell', 'row'].includes(role)) {
          part += `[role="${role}"]`;
        }
        const parent = current.parentElement;
        if (parent) {
          const siblings = Array.from(parent.children).filter((child) => child.nodeName === current.nodeName);
          if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
        }
        parts.unshift(part);
        current = current.parentElement;
      }
      return parts.join(' > ');
    };
    const textWithoutControls = (element) => {
      if (!element) return '';
      const clone = element.cloneNode(true);
      clone.querySelectorAll('input,textarea,select,button,script,style').forEach((node) => node.remove());
      return normalize(clone.textContent).replace(/^\*+/, '').trim();
    };
    const labelFor = (element) => {
      const explicit = element.id ? document.querySelector(`label[for="${CSS.escape(element.id)}"]`) : null;
      const labelledBy = element.getAttribute('aria-labelledby');
      const labelledByText = labelledBy
        ? labelledBy.split(/\s+/).map((id) => document.getElementById(id)?.innerText).filter(Boolean).join(' ')
        : '';
      const formItem = element.closest(
        '.ant-form-item,.wea-form-item,.wea-field-wrapper,.wea-new-top-req,.form-item,.field,.el-form-item,.row,.ant-row'
      );
      const nearbyLabel = formItem?.querySelector('label,.ant-form-item-label,.wea-label,.el-form-item__label');
      const candidates = [
        element.getAttribute('aria-label'),
        labelledByText,
        explicit?.innerText,
        nearbyLabel?.innerText,
        element.getAttribute('placeholder'),
        element.getAttribute('name'),
        element.id,
        textWithoutControls(formItem)
      ].map(normalize).filter(Boolean);
      return candidates[0] || '';
    };
    const requiredFor = (element) => {
      const container = element.closest('.ant-form-item,.wea-form-item,.form-item,.field,.el-form-item,.row,.ant-row');
      const markerText = normalize(container?.innerText).slice(0, 180);
      return Boolean(
        element.required ||
          element.getAttribute('aria-required') === 'true' ||
          container?.querySelector('.ant-form-item-required,.wea-required,.required,.is-required') ||
          /^\*/.test(markerText) ||
          /必填|required/i.test(markerText)
      );
    };
    const roleOrType = (element) => {
      const tag = element.tagName.toLowerCase();
      const type = element.getAttribute('type') || '';
      const role = element.getAttribute('role') || '';
      if (type === 'file') return 'file';
      if (type === 'checkbox') return 'checkbox';
      if (type === 'radio') return 'radio';
      if (['date', 'datetime-local', 'month'].includes(type)) return 'date';
      if (tag === 'select') return 'select';
      if (tag === 'textarea') return 'textarea';
      if (role === 'combobox' || element.className?.toString().includes('select')) return 'combobox';
      if (role === 'textbox' || tag === 'input') return 'text';
      if (element.getAttribute('contenteditable') === 'true') return 'rich-text';
      return role || tag;
    };
    const dangerTerms = ['提交', '批准', '审批', '同意', '付款', '支付', '删除', '作废', '发布', '发送', 'submit', 'approve', 'pay', 'delete', 'publish', 'send'];
    const safeIntentTerms = ['查询', '搜索', '筛选', '选择', '添加', '新增行', '展开', '下一页', '上一页', '确定', '取消', 'search', 'query', 'select', 'next', 'previous'];
    const classifyButton = (text) => {
      const lowered = String(text || '').toLowerCase();
      if (dangerTerms.some((term) => lowered.includes(term.toLowerCase()))) return 'dangerous';
      if (safeIntentTerms.some((term) => lowered.includes(term.toLowerCase()))) return 'interactive';
      return 'unknown';
    };
    const rectFor = (element) => {
      const rect = element.getBoundingClientRect();
      return {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        width: Math.round(rect.width),
        height: Math.round(rect.height)
      };
    };
    const fieldElements = Array.from(
      document.querySelectorAll('input,textarea,select,[contenteditable="true"],[role="combobox"],[role="textbox"]')
    );
    const fields = fieldElements.filter(isVisible).map((element, index) => {
      const tag = element.tagName.toLowerCase();
      const options = tag === 'select'
        ? Array.from(element.options).map((option) => ({ label: normalize(option.text), value: option.value }))
        : [];
      const container = element.closest('.ant-form-item,.wea-form-item,.form-item,.field,.el-form-item,.row,.ant-row');
      const nearbyButtons = Array.from(container?.querySelectorAll('button,[role="button"],.ant-btn,.wea-button') || [])
        .filter(isVisible)
        .map((button) => normalize(button.innerText || button.getAttribute('aria-label') || button.getAttribute('title')))
        .filter(Boolean);
      return {
        index,
        label: labelFor(element),
        selector: cssPath(element),
        tag,
        kind: roleOrType(element),
        type: element.getAttribute('type') || element.getAttribute('role') || tag,
        name: element.getAttribute('name') || '',
        id: element.id || '',
        placeholder: element.getAttribute('placeholder') || '',
        required: requiredFor(element),
        disabled: Boolean(element.disabled || element.getAttribute('aria-disabled') === 'true'),
        readonly: Boolean(element.readOnly || element.getAttribute('aria-readonly') === 'true'),
        value: normalize(element.value ?? element.textContent ?? '').slice(0, 300),
        options,
        nearbyButtons,
        lookupCandidate: roleOrType(element) === 'combobox' || nearbyButtons.some((text) => /查询|搜索|选择|search|select/i.test(text)),
        rect: rectFor(element)
      };
    });
    const buttons = Array.from(document.querySelectorAll('button,[role="button"],.ant-btn,.wea-button,a[role="button"]'))
      .filter(isVisible)
      .map((element, index) => {
        const text = normalize(element.innerText || element.getAttribute('aria-label') || element.getAttribute('title'));
        return {
          index,
          text,
          selector: cssPath(element),
          disabled: Boolean(element.disabled || element.getAttribute('aria-disabled') === 'true'),
          intent: classifyButton(text),
          rect: rectFor(element)
        };
      })
      .filter((button) => button.text || button.selector);
    const links = Array.from(document.querySelectorAll('a[href]'))
      .filter(isVisible)
      .slice(0, 120)
      .map((element, index) => ({
        index,
        text: normalize(element.innerText || element.getAttribute('title')),
        href: element.href,
        selector: cssPath(element)
      }));
    const tables = Array.from(document.querySelectorAll('table,.ant-table,.el-table,.wea-table,[role="table"],[role="grid"]'))
      .filter(isVisible)
      .map((element, index) => {
        const headers = Array.from(element.querySelectorAll('th,[role="columnheader"]')).map((cell) => normalize(cell.innerText));
        const rows = Array.from(element.querySelectorAll('tbody tr,[role="row"]')).map((row) =>
          Array.from(row.querySelectorAll('td,[role="gridcell"],[role="cell"]')).map((cell) => normalize(cell.innerText))
        ).filter((row) => row.some(Boolean));
        return {
          index,
          selector: cssPath(element),
          headers,
          rowCount: rows.length,
          sampleRows: rows.slice(0, 25),
          textSample: normalize(element.innerText).slice(0, 1200)
        };
      });
    const dialogs = Array.from(document.querySelectorAll('.ant-modal,.el-dialog,[role="dialog"],.wea-dialog'))
      .filter(isVisible)
      .map((element, index) => ({
        index,
        selector: cssPath(element),
        title: normalize(element.querySelector('.ant-modal-title,.el-dialog__title,[role="heading"]')?.innerText),
        textSample: normalize(element.innerText).slice(0, 1000)
      }));
    const pagination = Array.from(document.querySelectorAll('.ant-pagination,.el-pagination,.wea-pagination,[aria-label*="pagination" i]'))
      .filter(isVisible)
      .map((element, index) => ({
        index,
        selector: cssPath(element),
        text: normalize(element.innerText),
        nextSelector: cssPath(element.querySelector('.ant-pagination-next,.el-pager + button,[aria-label*="next" i]'))
      }));
    return {
      title: document.title || '',
      url: location.href,
      textSample: normalize(document.body?.innerText).slice(0, 1500),
      fields,
      buttons,
      links,
      tables,
      dialogs,
      pagination
    };
  });
  return {
    ...surface,
    url: redactUrl(surface.url),
    links: surface.links.map((link) => ({ ...link, href: redactUrl(link.href) }))
  };
}

export function diffFieldValues(before, after) {
  const keyFor = (field) => field.selector || field.id || field.name || `${field.label}:${field.index}`;
  const beforeMap = new Map((before?.fields || []).map((field) => [keyFor(field), field]));
  return (after?.fields || [])
    .map((field) => {
      const previous = beforeMap.get(keyFor(field));
      if (!previous) return null;
      if (previous.value === field.value) return null;
      return {
        label: field.label,
        selector: field.selector,
        before: previous.value,
        after: field.value
      };
    })
    .filter(Boolean);
}
