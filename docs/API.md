# API

服务默认监听 `http://127.0.0.1:8787`。

## GET /api/session/status

返回浏览器会话状态、Profile 路径、最近登录页截图。

## POST /api/session/open-login

请求：

```json
{
  "system": "oa",
  "pageId": "oa-portal"
}
```

PDM 可直接传入用户在本机前端粘贴的 SSO/callback URL：

```json
{
  "system": "pdm",
  "url": "https://pdm.megarobo.info/oauth/callback?code=..."
}
```

打开指定页面。如果检测到登录页，会在 `.runtime/login-screenshots` 生成截图，并返回截图 URL。

返回值会脱敏 `authCode`、`code`、`token`、`ticket` 等参数。不要把一次性授权 URL 发到聊天里，建议只粘贴到本地前端。

## POST /api/oa/scan

请求：

```json
{
  "pageId": "oa-workflow-458"
}
```

或：

```json
{
  "url": "https://oa.megarobo.info/..."
}
```

返回：

- `requiresLogin`：是否疑似跳到登录页。
- `fields`：页面字段，包含 label、selector、required、value、options。
- `buttons`：页面按钮。
- `apiCalls`：页面加载期间出现的 XHR/fetch 请求。
- `screenshotUrl`：登录或失败时的截图。

## POST /api/oa/fill

请求：

```json
{
  "pageId": "oa-workflow-458",
  "values": {
    "项目号": "C2-0225002",
    "WBS编码": "C2-0225002.06.01"
  },
  "attachments": [
    {
      "label": "附件",
      "path": "D:\\\\Desktop\\\\example.xlsx"
    }
  ],
  "saveDraft": true
}
```

字段 key 可以是扫描出的 label、name、placeholder，也可以在后续 `config/field-mappings.json` 中固化业务字段。

## POST /api/pdm/query

请求：

```json
{
  "materialCode": "4000059295",
  "maxPages": 2,
  "url": "https://pdm.megarobo.info/masterdata/master-data-material"
}
```

或：

```json
{
  "materialName": "人力外包",
  "maxPages": 2
}
```

也支持：

```json
{
  "specificationModel": "18-5019",
  "materialGroupCode": "407001",
  "brand": "Sartorius",
  "maxPages": 1
}
```

返回 PDM 物料分页查询结果：

- `query.filters`：实际筛选条件。
- `search.total`、`search.totalPages`、`search.fetchedPages`、`search.truncated`：分页摘要。
- `rows`：PDM 接口返回的原始完整字段。
- `organizedRows`：按中文字段名整理后的结果。

`url` 可选。若 PDM 必须通过钉钉工作台或企业 SSO 入口进入，可以把钉钉实际打开的 PDM URL 传入这里。

## POST /api/pdm/login-diagnose

请求：

```json
{
  "waitMs": 8000,
  "url": "https://pdm.megarobo.info/masterdata/master-data-material"
}
```

打开 PDM 页面并记录自动化 Edge 页面内发生的跳转、document/xhr/fetch 请求、响应摘要、可见字段、可见按钮、截图和 Cookie 名称摘要。

安全边界：

- 不读取钉钉本地进程。
- 不抓取系统代理流量。
- 不返回 Cookie 值。
- 对 token、ticket、session、password 等敏感字段做脱敏。

## POST /api/pdm/auth-probe

请求：

```json
{
  "url": "https://pdm.megarobo.info/masterdata/master-data-material"
}
```

尝试打开 PDM 已暴露的登录路由，并尝试点击页面上的企业 SSO 登录按钮。返回每个路由的截图、可见字段、按钮和跳转结果。

安全边界同 `/api/pdm/login-diagnose`：只走浏览器页面流程，不抓取钉钉本地流量，不返回凭证值。
