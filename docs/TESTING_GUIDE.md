# OAAssistant — 测试全流程(mock + 真机)Step by Step

> 三个层级,从快到全:**Level 1 纯离线单测**(秒级)→ **Level 2 mock 全栈**(无需登录,点完整 UI)→ **Level 3 真机**(需登录 Edge + 公司网)。
> 架构与 debug 见 [`ARCHITECTURE.md`](ARCHITECTURE.md)。**全程只存草稿,永不自动提交。**

---

## 0. 一次性准备

```bash
cd <repo>                      # 本机:/Users/yuanhz/Desktop/Scraps/OAAssistant

# Node 依赖
npm install

# 编排层 mac venv(不要用仓库根 .venv,那是旧 Windows venv)
python3.12 -m venv orchestrator/.venv
orchestrator/.venv/bin/pip install -r orchestrator/requirements.txt

# DeepSeek key(LLM 必需 —— mock 模式也要,classify_goal/unit_check 必调)
cp orchestrator/.env.example orchestrator/.env
# 然后编辑 orchestrator/.env,填入:
#   DEEPSEEK_API_KEY=sk-...
#   DEEPSEEK_MODEL=deepseek-v4-pro
```

> 验证 venv:`orchestrator/.venv/bin/python -c "import fastapi, langgraph, openpyxl; print('ok')"`

---

## Level 1 — 纯离线单测(无需任何服务 / 无需 key / 无需网络)

最快的 sanity。LLM 被 stub,后端用 MockExecutor。

```bash
# Node 语法门(唯一的 Node 验证步)
npm run check

# 编排层离线套件(逐个跑,各 <1s)
cd orchestrator
for t in smoke stage2 stage3 chat_demo inventory wbs router bff; do
  .venv/bin/python tests/$t.py && echo "  ↑ $t PASS" || echo "  ↑ $t FAIL"
done
```

**期望**:`npm run check` 无输出即通过;8 个测试都打印 `ALL … PASSED`。
- `router.py` 覆盖:三流 fan-out(412/89/458)、22 列 458 附件、WBS 分桶、缺口 note、PDM 拦截、缺 registry 跳过、归还 414、单位误用、**别称解析**。
- `bff.py` 覆盖:health、画像往返、chat SSE 出草稿、needs_input。

---

## Level 2 — mock 全栈(3 进程,无需登录 Edge,点完整四环节)

用来**检查从头到尾的布置效果**。OA/PDM/库存是假后端,但 WBS registry 是真的(你在 UI 改的能被聊天用上),LLM 是真的。

### 2.1 起三个进程(各开一个终端,或后台 &)

```bash
# 终端 A:Node(:8787) —— mock 模式不登录,但 WBS registry / 代理端点需要它
npm start

# 终端 B:BFF 网关(:8788) —— 需 orchestrator/.env 的 key
PYTHONPATH=orchestrator orchestrator/.venv/bin/uvicorn oa_orchestrator.bff:app --port 8788

# 终端 C:前端静态服务器(:5500)
cd frontend && python3 -m http.server 5500
```

打开浏览器:**http://127.0.0.1:5500**。顶栏徽章应显示「在线」,后端开关选「离线 mock」。

### 2.2 走四环节

1. **配置抽屉 → WBS 管理**(点右上「配置」):新增一条 WBS,例如
   - WBS编码 `C2-0225002.06.01`、别称 `传感器项目, SA探针`、需求工厂代码 `1010`、成本中心 `CC-1010-01`、采购人 `ZN092-张三`、库存地点名称 `实验室仓`、库存地点SAP `H001`、采购类型 `项目物资采购申请` → 保存。
   - (mock 库存里 4000059295=项目库存 Q、4000023659=公共仓;别称/cost center 走你刚存的这条。)
2. **配置抽屉 → 用户设置**(可选):填画像默认值,保存。
3. **配置抽屉 → 初始化**:mock 模式可跳过(无需登录)。关掉抽屉。
4. **右侧采购需求表**:默认两行(WBS 写**别称**「传感器项目」试解析),或自己填。保持「保存草稿」**不勾**(dry-run)。点 **「发起申请 ▸」**。

### 2.3 期望(左侧对话)
- 用户气泡 → 助手气泡里 **运行轨迹 chips** 实时生长:读取需求 → 解析WBS别称 → 识别意图 → 校验物料 → 单位校验 → 查库存 → 分配路由 → 补全+生成附件 → 填单(草稿) → 汇总。
- **完成 · 草稿 N 张**,彩色卡片:
  - `412 出库 · WBS C2-0225002.06.01`(别称已解析)· 物料×数量 · ✓已填(dry-run)
  - `458 采购 · …`(若有缺口)· 缺口 note。
- classify_goal 调了真 DeepSeek(thinking 模型,首个 LLM 节点可能要几秒~几十秒,属正常)。

> 排错:草稿「跳过 needsInput costCenter」= 该 WBS 没维护成本中心(回 WBS 管理补);徽章离线 = BFF 没起;报 LLM required = key 没配。更多见 [`ARCHITECTURE.md`](ARCHITECTURE.md) 第 8 节 Debug 锦囊。

---

## Level 3 — 真机全流程(需登录 Edge + 公司内网)

把 executor 换成 `http-node`,对真实 OA/PDM/库存填真草稿(**仍默认 dry-run 只填不存**)。

### 3.1 起服务(SSO 交接模式)

```bash
# 终端 A:Node,sso-handoff 模式 + 自动拉起托管 Edge
MEGANT_EDGE_PROFILE_MODE=sso-handoff MEGANT_AUTO_LAUNCH_EDGE=1 npm start
#   Windows 额外:钉钉 SSO Relay 见 docs/SSO_HANDOFF.md;mac 直接在托管 Edge 里手动登录。

# 终端 B、C:同 Level 2(BFF + 前端)
```

### 3.2 登录(前端 → 配置抽屉 → 初始化)
1. 顶栏后端开关切到 **真机(http-node)**。
2. 配置抽屉 → 初始化 → **打开 OA 登录** → 在弹出的**托管 Edge** 里扫码/SSO 完成登录 → **检测 OA**,绿灯。
3. 同样 **打开 PDM 登录 → 检测 PDM**,绿灯。
4. 程序只缓存浏览器登录态,不读 token/cookie。

### 3.3 备好 WBS 主数据
配置抽屉 → WBS 管理:确保用到的每个 WBS 都维护了 **成本中心(412 用)/ 库存地点(89、414 用)/ 采购人 + 送货地址 + 采购类型(458 用)/ 别称(可选)**。`是否为项目型`、`采购类型`、`附件需求类型` 来自后端选项目录下拉。否则对应草稿会被「跳过 needsInput」或使用目录默认值。

### 3.4 dry-run(先只填不存,核对!)
右侧填真实需求行 → **不勾保存草稿** → 发起申请。逐项核对:
- **PDM 校验**:物料编码都存在且启用(坏码会停在 needs_input)。
- **单位校验**:需求单位 vs PDM 基本单位;包装误用会停下让你确认。
- **库存路由**:草稿的 412/89/458 分流是否符合真实库存(SOBKZ:Q=项目库存→可能 89;空=公共仓→412;无库存→458)。
- **WBS 分桶**:不同 WBS 拆成不同草稿;89 转出=源项目 WBS、转入=需求 WBS。
- **458 附件**:`prepare` 生成的采购申请 Excel(`.runtime/orchestrator/<thread>/attachments/`)列是否被 OA 接受。

### 3.5 落草稿(确认无误后)
勾 **保存草稿** → 发起申请。草稿卡显示 `✓ <requestId>` + 可点链接。
- 然后**人工**打开 OA 核对每张草稿,**永不在程序里提交**;提交/审批永远人工。

> ⚠ 真机已知待验证点(见 [`ARCHITECTURE.md`](ARCHITECTURE.md) 第 6 节 进度状态):458 导入是否需要附件的 5 个参考页签;公共仓/无库存分支的真实 SOBKZ;首次跑务必 dry-run。

---

## 附:CLI 路径(无前端)

```bash
# mock(离线假后端;LLM 仍需 key)
PYTHONPATH=orchestrator orchestrator/.venv/bin/python -m oa_orchestrator.run \
  --executor mock --mode acquire --excel <需求表.xlsx> --request "采购这些物料"

# 真机(先按 3.1/3.2 起 Node 并登录),默认 dry-run;加 --save 落草稿
PYTHONPATH=orchestrator orchestrator/.venv/bin/python -m oa_orchestrator.run \
  --executor http-node --mode acquire --excel <需求表.xlsx> --request "采购这些物料"
```
需求表 sheet 名 `项目需求填写界面`,表头行 1、数据行 3+,列:`需求工厂代码 | WBS编码 | 项目定义 | 物料编码 | 物料名称 | 需求数量 | 基本计量单位 | MRP控制者`(WBS 列可写别称)。审计落 `.runtime/orchestrator/<thread>/run.json`。

终端 REPL 版:`python -m oa_orchestrator.chat`。

---

## 清理

```bash
# 停服务
pkill -f "src/server.js"; pkill -f "uvicorn oa_orchestrator"; pkill -f "http.server 5500"
# 清运行产物(可选)
rm -rf .runtime/orchestrator/chat-* .runtime/orchestrator/router-*
```
