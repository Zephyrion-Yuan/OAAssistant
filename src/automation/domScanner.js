export async function waitForSettledPage(page) {
  await page.waitForLoadState('domcontentloaded').catch(() => {});
  await page.waitForLoadState('networkidle', { timeout: 12000 }).catch(() => {});
  await page.waitForTimeout(1200);
}

export async function detectLoginPage(page) {
  return page.evaluate(() => {
    const text = (document.body?.innerText || '').replace(/\s+/g, ' ').slice(0, 3000);
    const url = location.href;
    const title = document.title || '';
    const loginHints = [
      '登录',
      '扫码',
      '二维码',
      '钉钉',
      'DingTalk',
      'login',
      'sign in',
      'sso'
    ];
    const hasLoginHint = loginHints.some((hint) => {
      const source = `${url} ${title} ${text}`;
      return source.toLowerCase().includes(hint.toLowerCase());
    });
    const hasFormSurface = document.querySelectorAll('input,textarea,select,button,[role="button"]').length > 0;
    const hasBusinessSurface = /workflow|material|物料|采购|出库|申请|表单/.test(text);
    return {
      requiresLogin: hasLoginHint && !hasBusinessSurface,
      title,
      url,
      textSample: text.slice(0, 500),
      hasFormSurface
    };
  });
}

export async function scanDom(page) {
  return page.evaluate(() => {
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
        const name = current.getAttribute('name');
        if (name && !/[:.[\]\s]/.test(name)) part += `[name="${name}"]`;
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
    const isRequired = (element) => {
      const container = element.closest('.ant-form-item,.wea-form-item,.form-item,.field,.el-form-item,.row,.ant-row');
      const markerText = normalize(container?.innerText).slice(0, 160);
      return Boolean(
        element.required ||
          element.getAttribute('aria-required') === 'true' ||
          container?.querySelector('.ant-form-item-required,.wea-required,.required,.is-required') ||
          /^[*＊]/.test(markerText) ||
          /必填|required/i.test(markerText)
      );
    };
    const fieldElements = Array.from(
      document.querySelectorAll('input,textarea,select,[contenteditable="true"],[role="combobox"],[role="textbox"]')
    );
    const fields = fieldElements.filter(isVisible).map((element, index) => {
      const tag = element.tagName.toLowerCase();
      const options = tag === 'select'
        ? Array.from(element.options).map((option) => ({ label: normalize(option.text), value: option.value }))
        : [];
      const rect = element.getBoundingClientRect();
      return {
        index,
        label: labelFor(element),
        selector: cssPath(element),
        tag,
        type: element.getAttribute('type') || element.getAttribute('role') || tag,
        name: element.getAttribute('name') || '',
        id: element.id || '',
        placeholder: element.getAttribute('placeholder') || '',
        required: isRequired(element),
        disabled: Boolean(element.disabled || element.getAttribute('aria-disabled') === 'true'),
        readonly: Boolean(element.readOnly || element.getAttribute('aria-readonly') === 'true'),
        value: element.value ?? element.textContent ?? '',
        options,
        rect: {
          x: Math.round(rect.x),
          y: Math.round(rect.y),
          width: Math.round(rect.width),
          height: Math.round(rect.height)
        }
      };
    });
    const buttons = Array.from(document.querySelectorAll('button,[role="button"],.ant-btn,.wea-button'))
      .filter(isVisible)
      .map((element) => ({
        text: normalize(element.innerText || element.getAttribute('aria-label') || element.getAttribute('title')),
        selector: cssPath(element),
        disabled: Boolean(element.disabled || element.getAttribute('aria-disabled') === 'true')
      }))
      .filter((button) => button.text || button.selector);
    const tables = Array.from(document.querySelectorAll('table,.ant-table,.el-table,.wea-table'))
      .filter(isVisible)
      .map((element) => ({
        selector: cssPath(element),
        textSample: normalize(element.innerText).slice(0, 1000)
      }));
    return {
      url: location.href,
      title: document.title,
      fields,
      buttons,
      tables
    };
  });
}

export async function extractTables(page) {
  return page.evaluate(() => {
    const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim();
    const tableNodes = Array.from(document.querySelectorAll('table'));
    const htmlTables = tableNodes.map((table) => {
      const headers = Array.from(table.querySelectorAll('thead th')).map((cell) => normalize(cell.innerText));
      const bodyRows = Array.from(table.querySelectorAll('tbody tr')).map((row) =>
        Array.from(row.querySelectorAll('td')).map((cell) => normalize(cell.innerText))
      ).filter((row) => row.some(Boolean));
      return { headers, rows: bodyRows };
    }).filter((table) => table.headers.length || table.rows.length);

    if (htmlTables.length) return htmlTables;

    const grid = document.querySelector('.ant-table,.el-table,.wea-table,[role="table"],[role="grid"]');
    if (!grid) return [];
    const headers = Array.from(grid.querySelectorAll('th,[role="columnheader"]')).map((cell) => normalize(cell.innerText));
    const rows = Array.from(grid.querySelectorAll('tbody tr,[role="row"]')).map((row) =>
      Array.from(row.querySelectorAll('td,[role="gridcell"],[role="cell"]')).map((cell) => normalize(cell.innerText))
    ).filter((row) => row.some(Boolean));
    return [{ headers, rows }];
  });
}
