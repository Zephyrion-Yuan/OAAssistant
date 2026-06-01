# 登录流程脚本

本项目固定为两套登录模式：

- OA：工具托管扫码活会话。
- PDM：普通 Edge 通过钉钉工作台 SSO 登录后，缓存 Edge Profile。

## OA 脚本

启动 OA 扫码登录：

```powershell
npm.cmd run oa:login:start
```

测试 OA 活会话：

```powershell
npm.cmd run oa:login:test
```

注意：

- 这两个命令需要本地服务 `npm.cmd start` 已经运行。
- OA 登录发生在工具托管 Edge 中。
- 登录成功后不要关闭该 Edge，不要重启服务。

## PDM 脚本

缓存 PDM Profile：

```powershell
npm.cmd run pdm:profile:cache
```

测试 PDM 缓存登录态：

```powershell
npm.cmd run pdm:profile:test
```

PDM 正确流程：

1. 在普通 Edge 中通过钉钉工作台进入 PDM，并确认能看到“物料查询”。
2. 关闭所有普通 Edge 窗口。
3. 执行 `npm.cmd run pdm:profile:cache`。脚本会先清理无窗口 Edge 后台进程，再缓存 Profile。
4. 执行 `npm.cmd run pdm:profile:test`。脚本会先清理无窗口 Edge 后台进程，再使用缓存 Profile 测试 PDM 登录态。

## 前端按钮

打开：

```text
http://127.0.0.1:8787
```

页面分为两个流程：

- `OA 登录流程`：打开 OA 扫码、测试 OA 活会话、诊断 OA 会话。
- `PDM 登录流程`：清 Edge 后台进程、缓存 PDM Profile、测试 PDM 缓存登录态。

## 安全边界

- 不抓取钉钉本地请求。
- 不导出 Cookie/token/authCode/code。
- Profile 缓存只保存在本机 `.runtime`。
