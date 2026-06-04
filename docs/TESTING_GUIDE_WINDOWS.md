# OAAssistant Windows 测试指南

本文是 `docs/TESTING_GUIDE.md` 的 Windows/PowerShell 版本。所有命令默认在仓库根目录执行：

```powershell
Set-Location D:\Desktop\OAAssistant
```

安全边界保持不变：自动化只打开稳定业务 URL、只填写配置字段、最多保存草稿；提交、审批、付款、删除、发送等动作必须由用户在浏览器里人工完成。

## 0. 一次性准备

确认本机已有：

- Windows PowerShell
- Python 3.11+，可用 `python --version` 检查
- Node.js 20+，可用 `node --version` 检查
- Microsoft Edge

安装 Node 依赖并创建仓库根目录 `.venv`：

```powershell
python scripts\local_venv.py setup
```

安装 Python 编排层依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r .\orchestrator\requirements.txt
```

如果要跑需要真实 LLM 的流程，创建 `orchestrator\.env` 并填写 DeepSeek 配置：

```powershell
if (!(Test-Path .\orchestrator\.env)) {
  Copy-Item .\orchestrator\.env.example .\orchestrator\.env
}
notepad .\orchestrator\.env
```

至少需要：

```dotenv
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_MODEL=deepseek-v4-pro
```

验证 venv：

```powershell
.\.venv\Scripts\python.exe -c "import fastapi, langgraph, openpyxl; print('ok')"
```

## PowerShell 命令差异

mac/Linux 写法不要直接复制到 Windows PowerShell。

| mac/Linux 写法 | Windows PowerShell 写法 |
| --- | --- |
| `PYTHONPATH=orchestrator command` | `$env:PYTHONPATH = "orchestrator"; command` |
| `orchestrator/.venv/bin/python` | `.\.venv\Scripts\python.exe` |
| `orchestrator/.venv/bin/pip` | `.\.venv\Scripts\python.exe -m pip` |
| `export KEY=value` | `$env:KEY = "value"` |
| `rm -rf path` | `Remove-Item path -Recurse -Force` |
| `pkill -f name` | `Get-Process name | Stop-Process` 或按端口停止 |

如果想激活 venv：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

未激活 venv 也可以直接使用 `.\.venv\Scripts\python.exe`，这更稳定。

## Level 1: 离线单测

这些测试不需要 Edge、OA/PDM 登录、公司内网，也不需要真实 DeepSeek key。LLM 会在测试里被 stub。

先检查 Node 语法：

```powershell
npm.cmd run check
```

运行 Python 离线测试：

```powershell
$tests = @(
  "smoke",
  "stage2",
  "stage3",
  "chat_demo",
  "inventory",
  "wbs",
  "router",
  "bff"
)

foreach ($t in $tests) {
  & .\.venv\Scripts\python.exe ".\orchestrator\tests\$t.py"
  if ($LASTEXITCODE -ne 0) {
    throw "$t failed"
  }
  Write-Host "$t PASS"
}
```

可选：真实 DeepSeek smoke test。有 key 时会请求 DeepSeek；没有 key 时应跳过。

```powershell
.\.venv\Scripts\python.exe .\orchestrator\tests\llm_live.py
```

## Level 2: mock 全栈测试

用途：检查前端、BFF、Node 本地服务的联动。OA/PDM/库存走 mock，不需要登录 Edge；但聊天路由会调用真实 LLM，因此需要 `orchestrator\.env` 里有 DeepSeek key。

打开三个 PowerShell 窗口。

终端 A：Node 服务，端口 `8787`：

```powershell
Set-Location D:\Desktop\OAAssistant
npm.cmd start
```

终端 B：BFF 网关，端口 `8788`：

```powershell
Set-Location D:\Desktop\OAAssistant
$env:PYTHONPATH = "orchestrator"
.\.venv\Scripts\python.exe -m uvicorn oa_orchestrator.bff:app --host 127.0.0.1 --port 8788
```

终端 C：前端静态服务，端口 `5500`：

```powershell
Set-Location D:\Desktop\OAAssistant\frontend
..\.venv\Scripts\python.exe -m http.server 5500
```

打开：

```text
http://127.0.0.1:5500
```

检查：

- 顶栏后端状态应为在线。
- 后端模式选择离线/mock。
- 右侧需求表可填写或使用默认行。
- 保持“保存草稿”未勾选，先做 dry-run。
- 左侧对话应出现运行轨迹，例如读取需求、识别意图、校验物料、查库存、分配路由、生成草稿。

接口快速验证：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8787/api/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8788/api/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8788/docs
```

## Level 3: 真机全流程

用途：连接真实 OA/PDM/库存页面。需要公司网络、托管 Edge 里的人工登录、稳定业务 URL。默认先 dry-run，只填不存。

启动前先关闭所有普通 Edge 窗口和后台 Edge 进程。`sso-handoff` 会使用系统 Edge User Data 根目录下的专用 profile `MEGAntBot`；如果普通 Edge 仍在运行，这个 profile 根目录会被锁住，Playwright 启动后会立刻退出。

```powershell
Set-Location D:\Desktop\OAAssistant
npm.cmd run edge:close-all
```

终端 A：以 SSO handoff 模式启动 Node 和托管 Edge：

```powershell
Set-Location D:\Desktop\OAAssistant
npm.cmd run sso:start
```

这个命令会：

- 启动本地 Node 服务 `http://127.0.0.1:8787`
- 使用 Playwright 托管的 Microsoft Edge 专用 profile
- 自动打开本地页面
- 让用户在该 Edge 里手动完成 OA/PDM 登录

也可以手动设置环境变量后启动：

```powershell
$env:MEGANT_EDGE_PROFILE_MODE = "sso-handoff"
$env:MEGANT_AUTO_LAUNCH_EDGE = "1"
npm.cmd start
```

终端 B、C：沿用 Level 2 的 BFF 和前端启动命令。

登录检查流程：

1. 前端顶栏将后端模式切到真机/http-node。
2. 打开配置抽屉。
3. 点击打开 OA 登录，在托管 Edge 中手动完成登录，然后点击检测 OA。
4. 点击打开 PDM 登录，在托管 Edge 中手动完成登录或 SSO 跳转，然后点击检测 PDM。
5. 确认 OA/PDM 都显示可用后，关闭托管 Edge 和 Node，再缓存 PDM profile：

```powershell
# 停掉 8787 Node 服务；这会释放托管 Edge profile
$owner = (Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8787 -State Listen).OwningProcess
Stop-Process -Id $owner -Force

# 确认 Edge 已关闭；如仍有 Edge 进程，先确认没有未保存页面再关闭
npm.cmd run edge:close-all

# 生成 cached profile；必须缓存 sso:start 使用的 MEGAntBot profile
# 这一次缓存会同时包含 OA 和 PDM 登录态
$env:MEGANT_EDGE_PROFILE_NAME = "MEGAntBot"
npm.cmd run profile:cache

# 分别验证 OA / PDM cached profile 登录态
npm.cmd run oa:profile:test
npm.cmd run pdm:profile:test

# 可选总检查：同一个 cached profile 同时验证 OA + PDM
npm.cmd run profile:test-login

# 重新启动真机服务
npm.cmd run sso:start
```

6. OA 和 PDM cached profile 测试都通过后，再执行真实 dry-run。

执行真实需求前检查：

- WBS 管理里维护了成本中心、库存地点、采购人、送货地址、采购类型等主数据；`是否为项目型`、`采购类型`、`附件需求类型` 应从后端选项目录下拉选择。
- 需求表里的物料编码、数量、单位、WBS 都正确。
- 第一次真机运行不要勾选“保存草稿”。
- 运行结果里出现的草稿、附件和字段映射需要人工核对。

确认无误后才勾选“保存草稿”。程序仍然不提交 OA 表单，提交和审批必须人工完成。

## CLI 路径

mock CLI：

```powershell
$env:PYTHONPATH = "orchestrator"
.\.venv\Scripts\python.exe -m oa_orchestrator.run `
  --executor mock `
  --mode acquire `
  --excel "D:\path\需求表.xlsx" `
  --request "采购这些物料"
```

真机 CLI，先按 Level 3 启动 Node 并完成登录：

```powershell
$env:PYTHONPATH = "orchestrator"
.\.venv\Scripts\python.exe -m oa_orchestrator.run `
  --executor http-node `
  --mode acquire `
  --excel "D:\path\需求表.xlsx" `
  --request "采购这些物料" `
  --dry-run
```

终端 REPL：

```powershell
$env:PYTHONPATH = "orchestrator"
.\.venv\Scripts\python.exe -m oa_orchestrator.chat
```

BFF：

```powershell
$env:PYTHONPATH = "orchestrator"
.\.venv\Scripts\python.exe -m uvicorn oa_orchestrator.bff:app --host 127.0.0.1 --port 8788
```

## 常见问题

### `PYTHONPATH=orchestrator` 无法识别

这是 mac/Linux 写法。PowerShell 用：

```powershell
$env:PYTHONPATH = "orchestrator"
.\.venv\Scripts\python.exe -m uvicorn oa_orchestrator.bff:app --port 8788
```

### `orchestrator/.venv/bin/pip` 无法识别

Windows 本地默认使用仓库根 `.venv`，不是 `orchestrator\.venv`：

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\orchestrator\requirements.txt
```

### `Activate.ps1 cannot be loaded`

当前 PowerShell 进程放开脚本执行策略：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 端口被占用

查看端口占用：

```powershell
Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8787 -State Listen
Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8788 -State Listen
Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 5500 -State Listen
```

按端口停止进程：

```powershell
$ports = @(8787, 8788, 5500)
foreach ($port in $ports) {
  $conns = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue
  foreach ($conn in $conns) {
    Stop-Process -Id $conn.OwningProcess -Force
  }
}
```

### BFF 报 `No module named 'oa_orchestrator'`

没有设置 `PYTHONPATH`，或启动目录不是仓库根目录。使用：

```powershell
Set-Location D:\Desktop\OAAssistant
$env:PYTHONPATH = "orchestrator"
.\.venv\Scripts\python.exe -m uvicorn oa_orchestrator.bff:app --port 8788
```

### Node 依赖缺失

重新安装：

```powershell
npm.cmd install
```

或者重新执行本地 setup：

```powershell
python scripts\local_venv.py setup
```

## 清理

停止常见本地服务：

```powershell
Get-Process node -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process python -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -like "*OAAssistant*\.venv*" } |
  Stop-Process -Force
```

清理运行产物，保留 venv 和依赖：

```powershell
Remove-Item .\.runtime\orchestrator\chat-* -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item .\.runtime\orchestrator\router-* -Recurse -Force -ErrorAction SilentlyContinue
```

如需完全重建依赖：

```powershell
Remove-Item .\.venv -Recurse -Force
Remove-Item .\node_modules -Recurse -Force
python scripts\local_venv.py setup
.\.venv\Scripts\python.exe -m pip install -r .\orchestrator\requirements.txt
```
