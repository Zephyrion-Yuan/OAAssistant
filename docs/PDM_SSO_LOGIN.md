# PDM SSO 登录复用流程

PDM 的真实登录链路是钉钉 OAuth 到公司 SSO，再回调到 PDM。`authCode` 和 `code` 是一次性授权码，不应由本工具抓取、记录或展示。

工具不拦截钉钉到 Edge 的 SSO 链接。推荐流程是复用 Edge Profile 中已经完成的 PDM 登录态。

## 操作步骤

1. 关闭本工具服务，释放 Edge Profile。

   如果服务运行在 `http://127.0.0.1:8787`，可以在 PowerShell 里执行：

   ```powershell
   Get-NetTCPConnection -LocalPort 8787 -State Listen | Select-Object -ExpandProperty OwningProcess | Stop-Process
   ```

2. 关闭所有 Edge 窗口和后台 Edge 进程。

3. 在钉钉工作台里点击 PDM，让它正常打开系统 Edge 并完成 SSO 登录。

4. 登录成功后，在 Edge 中确认能进入 PDM 页面，尤其是左侧能看到“物料查询”。

5. 关闭所有 Edge 窗口。

6. 回到本仓库启动工具，复用当前 Edge Profile。该脚本会使用 Edge `User Data` 根目录，并指定 `Default` Profile：

   ```powershell
   npm.cmd run start:current-profile
   ```

7. 打开 `http://127.0.0.1:8787`，执行 PDM 查询或诊断。

## 为什么不能边开 Edge 边复用

Playwright 的持久化 Profile 和普通 Edge 同时使用同一个 Profile 时，经常会被浏览器锁定。因此建议“钉钉打开 Edge 完成登录 -> 关闭 Edge -> 工具复用 Profile”。

## 安全边界

- 不抓取钉钉本地请求。
- 不读取钉钉缓存或进程。
- 不导出浏览器 Cookie 值。
- 不记录 SSO URL 中的一次性授权码。
