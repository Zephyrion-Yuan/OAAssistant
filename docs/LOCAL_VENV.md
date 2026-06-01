# .venv 本机运行

当前默认运行方式为本机 `.venv`，暂不使用 Docker。

## 准备环境

需要本机已有：

- Python 3
- Node.js 20+
- Microsoft Edge

首次安装：

```powershell
python scripts/local_venv.py setup
```

该命令会创建 `.venv`，并执行 `npm install` 安装 Node 依赖。

## 启动

```powershell
python scripts/local_venv.py start
```

启动后打开：

```text
http://127.0.0.1:8787
```

## 钉钉 SSO 交接启动

如需让程序启动后自动打开 Playwright 托管 Edge，并让钉钉点击 SSO 后尽量进入这个 Edge，使用：

```powershell
npm.cmd run sso:start
```

启动前请关闭所有普通 Edge 窗口和后台进程，并确认 Windows 默认浏览器是 Microsoft Edge。详见 [SSO_HANDOFF.md](SSO_HANDOFF.md)。

## 登录流程

OA：

1. 点击“打开 OA 登录页”。
2. 在弹出的本机 Edge 中扫码登录。
3. 点击“检测 OA 是否有效”。

PDM：

1. 点击“打开 PDM 登录页”。
2. 在弹出的本机 Edge 中完成 PDM 登录或 SSO 跳转。
3. 点击“检测 PDM 是否有效”。

## Linux 说明

如果 Linux 机器安装了 Microsoft Edge，默认配置可以继续使用：

```bash
python3 scripts/local_venv.py setup
python3 scripts/local_venv.py start
```

如果 Linux 上暂时没有 Edge，可以在启动前改用 Playwright bundled Chromium：

```bash
export MEGANT_BROWSER_CHANNEL=bundled
python3 scripts/local_venv.py start
```

这会降低“必须使用 Edge”的一致性，但可以用于 Linux 兼容性验证。
