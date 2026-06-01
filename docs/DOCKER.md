# Docker 运行

当前已暂停将 Docker 作为默认运行方式；默认请使用 [LOCAL_VENV.md](LOCAL_VENV.md) 中的 `.venv` 本机运行流程。本文件仅作为后续恢复 Docker 兼容时的参考。

本项目的 Docker 模式面向 Linux 服务器或 Linux 桌面环境。容器内运行 Node 服务、Microsoft Edge、Xvfb 和 noVNC。

## 启动

```powershell
docker compose up --build
```

启动后访问：

- 控制台：`http://localhost:8787`
- 容器浏览器窗口：`http://localhost:7900/vnc.html?autoconnect=1&resize=scale`

控制台页面里也有“打开浏览器窗口”按钮。

## 登录流程

OA：

1. 打开控制台。
2. 点击“打开浏览器窗口”。
3. 点击“打开 OA 登录页”。
4. 在 noVNC 里的 Edge 窗口扫码登录。
5. 点击“检测 OA 是否有效”。

PDM：

1. 打开控制台。
2. 点击“打开浏览器窗口”。
3. 点击“打开 PDM 登录页”。
4. 在 noVNC 里的 Edge 窗口完成 PDM 登录或 SSO 跳转。
5. 点击“检测 PDM 是否有效”。

## 持久化

`docker-compose.yml` 使用 `megant-runtime` volume 持久化 `.runtime`，包括工具托管 Edge profile。容器重建后，只要 volume 不删除，OA/PDM 的浏览器登录态会尽量复用。

清空登录态：

```powershell
docker compose down -v
```

## 端口和环境变量

- `8787`：MEGAnt 控制台和 API。
- `7900`：noVNC 浏览器窗口。
- `MEGANT_EDGE_PROFILE_MODE=isolated`：容器内使用 `.runtime/edge-profile`。
- `MEGANT_BROWSER_CHANNEL=msedge`：使用 Linux 版 Microsoft Edge。
- `MEGANT_BROWSER_ARGS=--no-sandbox,--disable-dev-shm-usage`：容器内 Edge 启动参数。

## 限制

Docker 容器不能直接复用宿主机 Windows Edge profile，也不能直接接管宿主机钉钉客户端打开到本机 Edge 的 SSO 链接。Docker 模式下需要在 noVNC 提供的容器浏览器内完成登录，并依赖容器 volume 持久化该登录态。
