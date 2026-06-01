# MEGAnt SSO Relay Guide

本文记录当前已经走通的 Windows + 钉钉 SSO + Playwright Edge 交接流程。

目标效果：

1. 程序启动后自动打开 Playwright 托管的 Microsoft Edge。
2. 钉钉工作台点击 OA/PDM 的 SSO 入口。
3. SSO 链接进入 Playwright 托管 Edge，而不是普通默认 Edge。
4. 登录完成后，机器人继续使用该已认证 Profile 进入子页面和执行填单。

## 1. 准备

在项目目录执行：

```powershell
cd D:\Desktop\MEGAnt
npm.cmd install
python scripts/local_venv.py setup
```

## 2. 安装本地 SSO Relay

执行：

```powershell
npm.cmd run sso:install-relay
```

该命令会：

- 编译生成独立中继程序：

```text
D:\Desktop\MEGAnt\.runtime\sso-relay\MEGAntSSORelay.exe
```

- 注册 Windows 默认应用：

```text
MEGAnt SSO Relay
```

- 注册 HTTP/HTTPS 协议处理 ProgID：

```text
MEGAntSSORelayURL
```

中继程序的作用是把系统传入的 URL 交给本机服务：

```text
http://127.0.0.1:8787/api/sso/open
```

服务端会校验域名白名单，并只返回脱敏 URL。

## 3. 设置默认应用

执行安装命令后会自动打开 Windows 默认应用设置。

如果没有自动打开，可手动执行：

```powershell
start ms-settings:defaultapps
```

然后：

1. 在“默认应用”中找到 `MEGAnt SSO Relay`。
2. 点进去。
3. 将 `HTTP` 设置为 `MEGAnt SSO Relay`。
4. 将 `HTTPS` 设置为 `MEGAnt SSO Relay`。

如果只看到 `Node.js`，说明仍是旧注册状态。重新执行：

```powershell
npm.cmd run sso:install-relay
```

并关闭后重新打开 Windows 设置页面。

## 4. 启动前关闭 Edge

启动 SSO 交接模式前，先关闭所有 Edge 进程：

```powershell
npm.cmd run edge:close-all
```

成功时会看到类似：

```json
{
  "ok": true,
  "killedCount": 0,
  "visibleKilledCount": 0
}
```

`killedCount` 为 0 表示本来就没有 Edge 进程，也属于正常。

## 5. 启动 SSO 交接模式

执行：

```powershell
npm.cmd run sso:start
```

该命令会设置：

```text
MEGANT_EDGE_PROFILE_MODE=sso-handoff
MEGANT_EDGE_PROFILE_NAME=MEGAntBot
MEGANT_AUTO_LAUNCH_EDGE=1
```

并自动打开 Playwright 托管 Edge。

该 Edge 使用系统 Edge User Data 下的专用 Profile：

```text
C:\Users\<用户名>\AppData\Local\Microsoft\Edge\User Data\MEGAntBot
```

控制台地址：

```text
http://127.0.0.1:8787
```

## 6. 从钉钉点击 OA/PDM

保持 `npm.cmd run sso:start` 运行。

然后在钉钉工作台点击 OA 或 PDM 入口。

预期结果：

- 钉钉 SSO 链接进入 Playwright 托管 Edge。
- 不再打开普通 Edge。
- 每次新 SSO 链接会打开新标签页，不会替换已有标签页。
- 登录完成后，控制台中 OA/PDM 检测按钮可以检测到登录态。

## 7. 验证登录态

打开：

```text
http://127.0.0.1:8787
```

点击：

- `检测 OA 是否有效`
- `检测 PDM 是否有效`

成功时返回 `ok: true`。

## 8. 工作原理

链路如下：

```text
钉钉点击 SSO
  -> Windows HTTP/HTTPS 默认应用
  -> MEGAntSSORelay.exe
  -> node scripts/relay-url.js <url>
  -> POST http://127.0.0.1:8787/api/sso/open
  -> Playwright 托管 Edge 打开 URL
  -> OA/PDM 完成登录
```

中继器不会保存 SSO URL。

安全边界：

- 不保存原始 SSO URL。
- 不打印原始 SSO URL。
- 不读取 Cookie。
- 不导出 Cookie。
- 不读取 token。
- 不导出 token。
- 不自动填写账号密码。
- 不自动处理 MFA。
- 不自动提交业务表单。

## 9. 还原默认浏览器

测试结束后，如需还原默认浏览器：

```powershell
npm.cmd run sso:uninstall-relay
```

然后在 Windows 默认应用设置中，把 `HTTP` 和 `HTTPS` 改回：

```text
Microsoft Edge
```

## 10. 当前已实现能力

仓库现在包含三类能力：

1. 登录与会话管理
   - OA：使用 Playwright 托管 Edge 的活会话，人工扫码或 SSO 登录后保持 Edge 打开。
   - PDM：使用普通 Edge 完成 SSO 后缓存 profile，后续查询默认复用 `.runtime/edge-profile-cache/User Data/Default`。
   - SSO Relay：将钉钉工作台打开的 OA/PDM 链接导入 Playwright 托管 Edge，不保存、不打印、不回放原始 SSO URL。

2. 页面探索
   - 通用探索：`npm.cmd run explore:page`
   - PDM 缓存 profile 探索：`npm.cmd run pdm:explore`
   - 产物：`.runtime/exploration/*.json` 和 `.runtime/exploration/*.md`
   - 汇总文档：`docs/PAGE_EXPLORATION_FRAMEWORK.md`、`docs/EXPLORATION_RESULTS.md`

3. 已固化业务脚本
   - 采购申请 workflow 458：`npm.cmd run oa:purchase-from-excel`
   - 物资出库 workflow 412：`npm.cmd run oa:outbound-from-excel`
   - 物资入库 workflow 414：`npm.cmd run oa:inbound-from-excel`
   - 库存转储 workflow 89：`npm.cmd run oa:stock-transfer-from-excel`
   - PDM 主数据物料查询：`npm.cmd run pdm:query`

## 11. 常用命令速查

启动交接模式：

```powershell
cd D:\Desktop\MEGAnt
npm.cmd run edge:close-all
npm.cmd run sso:start
```

探索新 OA/PDM 页面：

```powershell
npm.cmd run explore:page -- --name "页面名称" --page-id page-id --url "https://oa.megarobo.info/..." --full
```

探索 PDM 页面并复用 PDM 缓存 profile：

```powershell
npm.cmd run pdm:explore -- --name "PDM master data material" --page-id pdm-master-data-material --url "https://pdm.megarobo.info/masterdata/master-data-material" --full
```

查询 PDM 物料：

```powershell
npm.cmd run pdm:query -- --material-code 4000059295 --max-pages 2
npm.cmd run pdm:query -- --material-name "传感器" --max-pages 5
npm.cmd run pdm:query -- --material-group-code 407001 --max-pages 3
```

运行检查：

```powershell
npm.cmd run check
```

## 12. 已归档页面文档

- `docs/explorations/oa-purchase-workflow-458/README.md`
- `docs/explorations/oa-outbound-workflow-412/README.md`
- `docs/explorations/oa-outbound-workflow-412/2026-05-11-material-outbound-flow.md`
- `docs/explorations/oa-inbound-workflow-414/README.md`
- `docs/explorations/oa-stock-transfer-workflow-89/README.md`
- `docs/explorations/pdm-master-data-material/README.md`

## 13. 给新 Codex 会话的接续提示

如果需要让新会话继续探索或实现页面，可以直接说明：

```text
请按照 D:\Desktop\MEGAnt\AGENTS.md 和 COMMANDS.md 的规则执行。
当前 cwd 是 D:\Desktop\MEGAnt。
我已经通过 Playwright Edge 登录好了系统。
请先使用现有 /api/explore/page 或 npm run explore:page 做无 interaction 探索，
不要点击提交/审批/付款/删除/发布/发送等危险按钮，
探索产物写入 .runtime/exploration/，
并把结论追加到 docs/EXPLORATION_RESULTS.md 或 docs/explorations/<页面>/README.md。
目标页面 URL：<粘贴 URL>
```

如果要让 Codex 先登录自身 CLI，单独运行 `codex login` 即可；这和 OA/PDM 登录态无关，不应把公司 SSO 链接、cookie 或 token 复制给 Codex。

## 14. 常见问题

### 仍然打开普通 Edge

检查：

1. `HTTP` 和 `HTTPS` 是否都设置为 `MEGAnt SSO Relay`。
2. `npm.cmd run sso:start` 是否仍在运行。
3. 是否执行过 `npm.cmd run edge:close-all`。
4. Windows 设置页是否缓存旧状态，关闭后重新打开。

### 默认应用里没有 MEGAnt SSO Relay

重新执行：

```powershell
npm.cmd run sso:install-relay
```

确认生成了：

```text
D:\Desktop\MEGAnt\.runtime\sso-relay\MEGAntSSORelay.exe
```

### 端口 8787 被占用

`sso:start` 会自动停止监听 8787 的旧 Node 服务。若仍失败，可手动检查：

```powershell
Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8787 -State Listen
```

### Edge Profile 被占用

先执行：

```powershell
npm.cmd run edge:close-all
```

再启动：

```powershell
npm.cmd run sso:start
```
