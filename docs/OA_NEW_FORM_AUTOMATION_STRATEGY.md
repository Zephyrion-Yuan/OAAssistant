# OA 新表单自动化策略

更新日期：2026-05-12

## 已掌握的通用操作知识

- 长期入口只保留 `#/main/workflow/req` 之后的业务参数，例如 `iscreate=1&workflowid=...`；不固化 `_rdm`、`preloadkey`、`timestamp`、`_key`。
- 表单真实字段来自 `POST /api/workflow/reqform/loadForm`；其中 `tableInfo` 可确定字段 ID、必填性、可编辑性、下拉选项、`browser.*` 类型和明细表字段。
- OA 浏览框统一用 `#field<id>span > div:nth-of-type(2) > button` 打开；明细行浏览框用 `#field<id>_<rowIndex>span > div:nth-of-type(2) > button`。
- 浏览框通用接口为 `/api/public/browser/condition/161` 和 `/api/public/browser/data/161`；搜索 input 经常有隐藏重名 ID，脚本必须使用 `:visible`。
- 选择浏览框结果后，页面通常通过 `reqDataInputResult` 或 `formula/assignValue` 联动回填字段，脚本应让页面 DOM 自己触发联动，不直接拼请求写数据。
- 明细输入框一般是 `#field<id>_<rowIndex>`；数量、库存地点、WBS 的 rowIndex 必须从实际可见行确认。
- 只能点击已验证的搜索、候选、普通字段、保存草稿；不自动点击提交、审批、付款、删除、发布、发送。

## 458/412/414/89 的经验沉淀

- 458 采购申请：Excel 标准化是入口，WBS 回填项目/PDT/BU，但是否项目型、采购类型、需求公司仍需显式设置。
- 412 出库：记账主体先按工厂选，公司相关字段会影响成本中心弹窗；成本中心需从 Excel MRP 控制者和用户部门推导；用途按 WBS 前缀配置；预留号按工厂/WBS 检索后生成明细。
- 414 入库：入库类型决定后续关联凭证弹窗；项目退料按项目编码/凭证号选择出库记录后生成明细；库存地点和数量仍需规则或用户输入。
- 89 库存转储：移动类型决定是否需要转出/转入 WBS；物料选择只回填物料描述、规格、单位，数量和库存地点由脚本填；页面当前只确认了已有明细行的填充方式。

## 新表单固化流程

1. 提取长期入口，更新 `config/pages.json`。
2. 用 `/api/explore/page` 做无 interaction 扫描，产物写入 `.runtime/exploration/`。
3. 用字段扫描或 `loadForm` 列出必填字段、可编辑字段、下拉选项、明细表字段。
4. 对每个浏览框分别做安全探索：打开、记录 condition/data 接口、检索字段、结果列、候选行。
5. 用一条测试数据选择候选，记录回填字段和联动接口。
6. 把业务规则分成配置默认值和运行时输入；无法唯一判断时返回 `needsInput=true`。
7. 固化脚本、运行静态检查、用不保存干跑验证；保存必须由显式配置开启。
8. 更新 `docs/EXPLORATION_RESULTS.md` 或对应 workflow 文档。

## 用户可提供的信息

- 一个创建页链接，以及一个已完成或草稿请求链接用于对照。
- 一份最小测试数据，最好包含 1 条正常数据和 1 条多候选/边界数据。
- 业务默认值：类型、用途、仓库、库存地点、成本中心、WBS、项目经理、是否抄送等。
- 多候选时的选择规则，或允许脚本返回候选让 agent 继续询问。
- 是否允许保存草稿；提交仍由人工完成。

## 有帮助的额外工具

- 已填请求读取器：输入 requestid，输出字段值、明细行、附件和关键接口摘要。
- 弹窗候选导出器：输入 selector/browser type 和搜索条件，导出候选 JSON。
- 明细行控件探测器：只识别新增/复制/删除明细行控件，不执行危险动作。
