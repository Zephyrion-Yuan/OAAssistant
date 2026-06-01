# OA workflow 自动化操作知识

更新时间：2026-05-12

## 安全边界

- 只使用 Playwright 托管的专用 Edge profile，人工完成 OA SSO 后再打开稳定业务 URL。
- 稳定入口只保留 `#/main/workflow/req` 之后的业务参数，如 `iscreate=1&workflowid=...`；不固化 `_rdm`、`preloadkey`、`timestamp`、`_key`。
- 探索和固化脚本可以打开浏览字段、检索、点选候选行、填充普通字段、保存草稿；不得自动点击 `提交`、审批、付款、删除、发布、发送。
- 新页面先跑 `/api/explore/page` 无 interaction 探索，再逐个做安全 interaction 探索；产物写入 `.runtime/exploration/` 并整理到 `docs/`。

## 已掌握的 OA 页面规律

- 表单字段的权威来源是 `POST /api/workflow/reqform/loadForm`，其中 `maindata`、`tableInfo`、`browserInfo`、`datajson` 和 `linkageCfg` 能确定字段 ID、必填性、可编辑性、下拉选项和联动关系。
- 普通 DOM 扫描通常只能识别可见 combobox 和输入框。OA 自定义浏览字段要按 `#field<id>span > div:nth-of-type(2) > button` 打开。
- `browser.*` 弹窗通用接口是：
  - `GET /api/public/browser/condition/161?...type=browser.xxx&fieldid=<fieldId>...`
  - `GET /api/public/browser/data/161?pageSize=10&current=1&...type=browser.xxx&fieldid=<fieldId>...`
- 选择浏览字段结果后，页面通常调用 `POST /api/workflow/linkage/reqDataInputResult`；这个接口会回填主表字段，并可能通过 `addDetailRow` 生成明细行。
- 明细行 input 采用 `#field<id>_<rowIndex>`；明细浏览字段按钮采用 `#field<id>_<rowIndex>span > div:nth-of-type(2) > button`。
- 下拉字段使用 `#weaSelect_N div[role="combobox"]`，需要先点击下拉，再按精确文本点选选项。
- 查询弹窗里的输入框可能存在重复 ID；脚本应优先使用 `:visible` 或限定在当前 `.ant-modal:visible` 内。

## 458 采购申请经验

- 入参是采购 Excel；先由 `scripts/purchase_excel.py` 标准化数据并生成附件，再由 `scripts/oa-purchase-from-excel.js` 填页面。
- WBS 浏览字段选中后会回填项目/PDT/BU 等信息，但 `是否为项目型`、`采购类型`、`需求公司` 仍需显式设置。
- 需求公司使用 `browser.xmcj_gsdm`，按工厂代码定位并校验公司名。
- 采购页最终动作是上传标准化附件并保存草稿；不提交。

## 412 出库申请经验

- 入参是采购 Excel 和用户部门。Excel helper 解析需求工厂、WBS、MRP 控制者，并在 MRP 控制者 sheet 中定位成本中心。
- `所属记账主体` 使用 `browser.xmcj_gsdm`，按需求工厂代码选择。
- `成本中心` 使用 `browser.CBZXGLGS`，必须在记账主体之后检索，检索值用成本中心名称。
- `用途` 使用 `browser.yt`，当前配置将 `R` 开头 WBS 映射到 `研发项目-研发领料`，`C` 开头映射到 `交付项目-厂内调试`。
- `预留号` 使用 `browser.ReservedInformationDate`，检索工厂 `WERKS` 和 WBS `ZYL3`；选中后调用 SAP 查询接口并生成明细。
- 明细生成后勾选所有物资行，按 SAP `LT_DATA[].BDMNG` 填申请数量，再按用户要求保存草稿。

## 新页面掌握方法

1. 提取稳定入口，更新 `config/pages.json`，删除一次性参数。
2. 运行无 interaction 探索，记录标题、按钮、字段、表格、初始 workflow 接口。
3. 从字段摘要或 `loadForm` 里列出必填字段、下拉选项、`browser.*` 类型和明细表字段。
4. 对每个浏览字段做单独安全探索：打开弹窗、记录 condition/data 接口、检索字段、结果列和候选行。
5. 选择一条测试候选行，观察 `reqDataInputResult` 回填哪些主表字段、生成哪些明细行。
6. 对明细必填字段做干跑填充，确认 selector、行号、数量规则和库存地点等依赖字段。
7. 把仍需用户确认的业务规则列成问题，例如类型映射、默认仓库、库存地点选择规则、数量取值、是否保存。
8. 固化脚本时只复用已验证 selector 和接口联动，输出运行报告和回填后页面链接。

## 414 入库脚本交互约定

`scripts/oa-inbound-from-excel.js` 已按“默认配置 + 运行时交互”实现项目退料入库：

- 默认入库类型：`项目退料`
- 默认出库凭证检索：Excel `项目定义` -> 弹窗 `项目编码`
- 默认数量规则：采购表 `物料编码 -> 需求数量`
- 默认允许保存；`--no-save` 可关闭保存

脚本不固化以下不稳定判断，会返回 `needsInput=true`：

- 项目编码命中多个出库物料凭证：返回候选 `voucherNumber/projectCode/projectName/applyDate/applicant`，调用方再用 `--voucher-number` 继续。
- 库存地点未提供或未匹配：返回库存地点候选，调用方再用 `--stock-location-name` 或 `--stock-location-sap` 继续。
- OA 明细物料无法从采购表唯一匹配数量：返回缺失/重复物料和采购表数量，调用方再用 `--quantity-overrides` 继续。

这类 `needsInput` 是 agent 和用户之间的交互协议，不视为脚本失败。
