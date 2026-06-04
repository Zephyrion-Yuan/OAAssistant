# 固定登录流程

## 总原则

- OA：扫码登录后只能依赖工具托管的活 Edge 会话。不要关闭工具打开的 Edge，不要重启服务。
- PDM：从钉钉工作台进入普通 Edge 后，把普通 Edge 的 Profile 缓存到 `.runtime`，后续 PDM 自动化使用缓存 Profile。
- 两套流程分开，不再混用同一个 Profile 策略。

## 启动服务

推荐用默认启动方式：

```powershell
npm.cmd start
```

默认使用 `.runtime/edge-profile` 作为工具托管的 Edge Profile，专门给 OA 活会话使用。

## OA：工具托管扫码活会话

前端：

1. 打开 `http://127.0.0.1:8787`。
2. 点击 `1. 打开 OA 扫码登录`。
3. 在工具弹出的 Edge 中扫码登录 OA。
4. 不关闭该 Edge，不重启服务。
5. 点击 `2. 测试 OA 活会话`。

命令行：

```powershell
npm.cmd run oa:login:start
npm.cmd run oa:login:test
```

OA portal 入口固定为：

```text
https://oa.megarobo.info/wui/index.html?#/main/portal/portal-1-1?menuIds=0,1&menuPathIds=0,1&_key=tcagna
```

## PDM：普通 Edge SSO 后缓存 Profile

前端：

1. 关闭工具弹出的 Edge 和普通 Edge。
2. 在普通 Edge 中从钉钉工作台进入 PDM，并确认能看到 `物料查询`。
3. 关闭普通 Edge。
4. 回到前端点击 `1. 清 Edge 后台进程`。
5. 点击 `2. 缓存 PDM Profile`。
6. 点击 `3. 测试 PDM 缓存登录态`。

命令行：

```powershell
npm.cmd run pdm:profile:cache
npm.cmd run pdm:profile:test
```

PDM 自动查询默认使用 `.runtime/edge-profile-cache/User Data/Default` 这个缓存 Profile。

## 注意事项

- 执行 PDM 缓存前必须关闭所有 Edge，包括工具托管 OA 的 Edge；否则 Profile 会被锁定。
- 如果只看到 `0 visible window(s)` 的 Edge 进程，前端的 `清 Edge 后台进程` 会关闭这些后台进程。
- 工具不抓取钉钉本地请求，不导出 Cookie/token/authCode/code。

## Windows sso-handoff：缓存并验证 OA + PDM

如果使用 `npm.cmd run sso:start`，登录发生在系统 Edge User Data 下的专用 profile `MEGAntBot`。真机测试前应缓存并验证这个 profile 的 OA 和 PDM 登录态：

```powershell
$env:MEGANT_EDGE_PROFILE_NAME = "MEGAntBot"
npm.cmd run profile:cache
npm.cmd run oa:profile:test
npm.cmd run pdm:profile:test
npm.cmd run profile:test-login
```

`profile:cache` 只需执行一次；`oa:profile:test` 和 `pdm:profile:test` 分别验证两套登录态，`profile:test-login` 做总检查。
