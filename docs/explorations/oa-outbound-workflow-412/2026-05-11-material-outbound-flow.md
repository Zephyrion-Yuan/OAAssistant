# OA 物资出库流程 workflowid=412：项目预留出库固化记录

记录日期：2026-05-11

## 入口

稳定创建入口：

```text
https://oa.megarobo.info/spa/workflow/static4form/index.html#/main/workflow/req?iscreate=1&workflowid=412&isagent=0&beagenter=0&f_weaver_belongto_userid=&f_weaver_belongto_usertype=0
```

保存后的长期查看入口按 `requestid` 生成：

```text
https://oa.megarobo.info/spa/workflow/static4form/index.html#/main/workflow/req?requestid=<requestid>
```

## 本轮探索产物

- 所属记账主体弹窗：`.runtime/exploration/2026-05-11T08-01-36-117Z-oa-workflow-412-company-browser-popup-oa.megarobo.info.*`
- 成本中心弹窗与联动：`.runtime/exploration/2026-05-11T08-02-21-722Z-oa-workflow-412-company-select-then-cost-center-popup-oa.megarobo.info.*`
- 成本中心名称检索：`.runtime/exploration/2026-05-11T08-04-33-466Z-oa-workflow-412-cost-center-visible-input-search-product-dev-acro-oa.megarobo.info.*`
- 仓库类型选择：`.runtime/exploration/2026-05-11T08-05-15-791Z-oa-workflow-412-warehouse-type-select-scan-oa.megarobo.info.*`
- 用途弹窗：`.runtime/exploration/2026-05-11T08-05-46-282Z-oa-workflow-412-purpose-browser-popup-oa.megarobo.info.*`
- 预留号初始弹窗：`.runtime/exploration/2026-05-11T08-06-26-136Z-oa-workflow-412-reservation-browser-popup-initial-oa.megarobo.info.*`
- 预留号检索：`.runtime/exploration/2026-05-11T08-09-16-654Z-oa-workflow-412-reservation-search-by-factory-and-wbs-oa.megarobo.info.*`
- 预留号点选后物资行：`.runtime/exploration/2026-05-11T08-11-16-612Z-oa-workflow-412-select-reservation-row-scan-material-rows-oa.megarobo.info.*`
- 完整前置链路：`.runtime/exploration/2026-05-11T08-13-13-050Z-oa-workflow-412-full-prerequisite-chain-select-scan-oa.megarobo.info.*`
- 物资勾选和数量填写：`.runtime/exploration/2026-05-11T08-15-15-682Z-oa-workflow-412-material-row-checkbox-and-quantity-scan-oa.megarobo.info.*`
- 保存草稿：`.runtime/exploration/2026-05-11T08-17-16-027Z-oa-workflow-412-save-draft-after-material-fill-scan-oa.megarobo.info.*`

## Excel 标准化输入

示例文件：`D:\Desktop\采购申请\项目采购申请-SA探针.xlsx`

解析规则固化在 `scripts/outbound_excel.py`：

- 主数据 sheet：`项目需求填写界面`，第 1 行表头，第 2 行说明，第 3 行起数据。
- 必须唯一的字段：`需求工厂代码`、`WBS编码`、`项目定义`、`MRP控制者`。
- 根据 `MRP控制者` sheet 将 MRP 编码映射到 MRP 描述，例如 `P22 -> ACRO`。
- 根据用户部门和 MRP 描述在 `成本中心` sheet 中定位成本中心短文本。示例用户部门 `ACRO产品开发部` 会归一到 `产品开发部(ACRO)`，公司 `1010` 下唯一成本中心为 `101BU06015`。

示例解析结果：

| 字段 | 值 |
| --- | --- |
| 需求工厂代码 | `1010` |
| WBS编码 | `C2-0225002.06.01` |
| MRP控制者 | `P22` |
| MRP描述 | `ACRO` |
| 成本中心名称 | `产品开发部(ACRO)` |
| 成本中心编号 | `101BU06015` |

## 页面字段和接口

### 所属记账主体

- selector：`#field7245span > div:nth-of-type(2) > button`
- 浏览类型：`browser.xmcj_gsdm`
- 数据接口：`GET /api/public/browser/data/161?...&type=browser.xmcj_gsdm&workflowid=412&fieldid=7245...`
- 结果列：`名称`、`编码`
- 示例：`1010 -> 苏州镁伽科技有限公司`，行 id 为 `2`
- 点选后联动：`POST /api/workflow/linkage/reqDataInputResult`，提交 `field7245=2`，`linkageid=3661`

### 成本中心

- selector：`#field7482span > div:nth-of-type(2) > button`
- 前置条件：必须先选择所属记账主体；接口参数会带 `gsdm_<currenttime>=1010`
- 浏览类型：`browser.CBZXGLGS`
- 检索输入：`input#con7457_value:visible`
- 检索参数：`con7457_value=<成本中心名称>&isFromAdvanceSearch=1`
- 结果列：`成本中心名称`、`成本中心`、`公司代码`、`利润中心`、`部门编码`、`成本中心组名称`
- 示例结果：`产品开发部(ACRO) | 101BU06015 | 1010 | PT22 | BU06015 | 苏州镁伽科技-研发`
- 点选后回填：成本中心、成本中心编号、PDT、PDT负责人

### 仓库类型

- selector：`#weaSelect_2 div[role="combobox"]`
- 示例选项：`鲲鹏仓库`
- 选择动作未触发 XHR，仅改变页面字段值。

### 用途

- selector：`#field12742span > div:nth-of-type(2) > button`
- 浏览类型：`browser.yt`
- 数据接口带 `chuklx_<currenttime>=1`，来自出库类型 `项目领料`
- 结果列：`用途`、`编码`、`用途说明`
- 已固化配置：`config/oa-workflow-412-outbound.json`

当前配置：

| WBS 前缀 | OA 用途文案 | 编码 |
| --- | --- | --- |
| `R` | `研发项目-研发领料` | `1009` |
| `C` | `交付项目-厂内调试` | `1011` |

### 预留号

- selector：`#field8260span > div:nth-of-type(2) > button`
- 浏览类型：`browser.ReservedInformationDate`
- 检索输入：
  - `input#WERKS:visible`：工厂
  - `input#ZYL3:visible`：WBS号
- 数据接口：`GET /api/public/browser/data/161?...&WERKS=1010&ZYL3=C2-0225002.06.01&type=browser.ReservedInformationDate&workflowid=412&fieldid=8260...`
- 结果列：`预留/相关需求的编号`、`预留项目编号`、`工厂(必填)`、`物料编号`、`物料描述`、`基本计量单位`、`需求数量`、`提货数`、`WBS 编号`、`存储地点`、`组件的需求日期`、`网络号`
- 示例检索结果：`30659 | 1 | 1010 | 4000059295 | Octet链霉亲和素SA传感器#18-5019 | 盒 | 2 | 0 | C2-0225002.06.01 | H001 | 2026-05-08 | 5025020`
- 点选后额外调用：`GET /api/querySAPActionApi/IF031?rsNum=30659&werks=1010&zyl1=281`
- `IF031` 返回 `LT_DATA` 明细，包含 `RSNUM`、`RSPOS`、`MATNR`、`MAKTX`、`BDMNG`、`ENMNG`、`MEINS`、`WERKS`、`LGORT`、`POSID`、`ZYL1` 等字段。

### 物资明细

- 明细表：`#oTable1`
- 可见勾选框：`#oTable1 input[type="checkbox"]:visible`
- 申请数量输入：`#field8315_<rowIndex>`
- 示例点选预留号后生成 1 行，`总共需求数量=2`，填写 `#field8315_0=2`；保存后页面将其格式化为 `2.000`。
- 固化脚本使用 `IF031` 的 `LT_DATA[].BDMNG` 按行填入申请数量。

## 保存

- 按钮 selector：`button:visible:has-text("保 存")`
- 保存接口：`POST /api/workflow/reqform/requestOperation`
- 关键请求字段：`src=save`、`type=save`、`workflowid=412`、`requestid=-1`
- 示例响应：`data.type=SUCCESS`，`data.resultInfo.requestid=1437117`
- 示例最终 URL 包含 `requestid=1437117`。脚本返回不含 `_key` 的长期查看链接：`https://oa.megarobo.info/spa/workflow/static4form/index.html#/main/workflow/req?requestid=1437117`
- 本流程只保存草稿，不点击 `提 交`，不执行审批、付款、删除、发布、发送。

## 固化命令

脚本文件：

- `scripts/outbound_excel.py`
- `scripts/oa-outbound-from-excel.js`

配置文件：

- `config/oa-workflow-412-outbound.json`

示例命令：

```powershell
npm.cmd run oa:outbound-from-excel -- --file "D:\Desktop\采购申请\项目采购申请-SA探针.xlsx" --user-department "ACRO产品开发部"
```

只填表不保存：

```powershell
npm.cmd run oa:outbound-from-excel -- --file "D:\Desktop\采购申请\项目采购申请-SA探针.xlsx" --user-department "ACRO产品开发部" --no-save
```
