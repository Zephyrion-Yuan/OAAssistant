# 钉钉 SSO 到 Playwright Edge 的交接模式

目标效果：

程序启动后先打开一个 Playwright 托管的 Microsoft Edge。用户从钉钉工作台点击 OA/PDM 的 SSO 入口时，Windows 将链接交给这个已经运行的 Edge 实例打开。登录成功后，机器人继续使用同一个 Profile 访问稳定业务页面和执行填单。

## 启动方式

先关闭所有普通 Edge 窗口和后台进程，然后执行：

```powershell
npm.cmd run edge:close-all
```

再启动交接模式：

```powershell
python scripts/local_venv.py sso-start
```

或：

```powershell
npm.cmd run sso:start
```

该模式会设置：

- `MEGANT_EDGE_PROFILE_MODE=sso-handoff`
- `MEGANT_EDGE_PROFILE_NAME=MEGAntBot`
- `MEGANT_AUTO_LAUNCH_EDGE=1`

也就是使用系统 Edge User Data 根目录下的专用 Profile `MEGAntBot`，并在服务启动后自动打开可见 Edge。

## 使用步骤

1. 确认 Windows 默认浏览器是 Microsoft Edge。
2. 关闭所有普通 Edge 窗口和后台 Edge 进程。
3. 执行 `npm.cmd run sso:start`。
4. 等待 Playwright 托管的 Edge 自动弹出。
5. 在钉钉工作台点击 OA 或 PDM 入口。
6. SSO 链接应进入这个已打开的 Edge 实例。
7. 完成登录后，在控制台点击“检测 OA 是否有效”或“检测 PDM 是否有效”。

## 为什么这样实现

Windows 对 `http/https` 默认浏览器关联有保护，不能可靠地由普通脚本静默改成自定义拦截器。更稳的方式是让 Playwright 启动系统 Edge User Data 根目录里的一个专用 Profile。此时钉钉调用默认 Edge 打开 URL 时，会优先交给已经运行的 Edge 实例处理。

该方式不会保存、打印、解密或上传 SSO URL。SSO URL 只在本机浏览器打开流程中短暂经过。

## 失败时检查

- 如果链接进入普通 Edge：说明启动前已有普通 Edge 实例，或默认浏览器不是 Edge。
- 如果 Playwright 启动失败：通常是普通 Edge 仍占用系统 Edge User Data 根目录，需要先关闭 Edge 后台进程。
- 如果登录后检测仍失败：确认钉钉入口确实打开在 `MEGAntBot` 这个可见 Profile 中。

## 默认浏览器中继器

如果钉钉点击 SSO 后仍没有进入 Playwright 托管的 Edge，说明 Windows/Edge 没有把外部 `https://...` 链接投递到当前 Playwright context。此时使用本地默认浏览器中继器：

```powershell
npm.cmd run sso:install-relay
```

然后在打开的 Windows 设置中：

1. 进入“默认应用”。
2. 找到 `MEGAnt SSO Relay`。
3. 将 `HTTP` 和 `HTTPS` 设置为 `MEGAnt SSO Relay`。
4. 保持 `npm.cmd run sso:start` 正在运行。
5. 再从钉钉点击 OA/PDM。

中继器不会保存 URL。它只会把收到的 URL 通过本地 `http://127.0.0.1:8787/api/sso/open` 交给 Playwright Edge，并且服务端会校验域名白名单、返回脱敏 URL。

每次新的 SSO URL 都会在 Playwright Edge 中打开新标签页，不会替换已有标签页。

测试结束后建议恢复默认浏览器：

```powershell
npm.cmd run sso:uninstall-relay
```

然后在 Windows 设置中把 `HTTP` 和 `HTTPS` 改回 Microsoft Edge。

## 本地 URL 交接 API

服务端提供一个本地调试/兜底接口：

```text
POST /api/sso/open
```

请求体：

```json
{
  "url": "https://sso.megarobo.tech/..."
}
```

接口会校验域名白名单，然后将 URL 打开到 Playwright 托管 Edge。返回值只包含脱敏 URL。

命令行兜底：

```powershell
npm.cmd run sso:relay-url -- "https://sso.megarobo.tech/..."
```

默认允许域名：

- `oa.megarobo.info`
- `pdm.megarobo.info`
- `pdm-api.megarobo.info`
- `sso.megarobo.tech`
- `megarobo.tech`
- `megarobo.info`

可通过环境变量覆盖：

```powershell
$env:MEGANT_SSO_ALLOWED_HOSTS="oa.megarobo.info,pdm.megarobo.info,sso.megarobo.tech"
```

## 安全边界

- 不保存 SSO URL。
- 不打印原始 SSO URL。
- 不读取或导出 Cookie。
- 不读取或导出 token。
- 不自动填写账号密码。
- 不自动处理 MFA。
- 不自动提交业务表单。
