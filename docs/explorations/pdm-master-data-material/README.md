# PDM 主数据物料查询

记录日期：2026-05-27

## 入口

- 稳定入口：`https://pdm.megarobo.info/masterdata/master-data-material`
- 旧入口：`https://pdm.megarobo.info/material/material-form`
- 页面标题：`物料管理 - MegaPDM`
- 登录方式：使用 `.runtime/edge-profile-cache/User Data/Default` 中已缓存的 PDM profile。探索和查询不读取 cookie、token、Authorization header 或本地存储凭证。

## 探索产物

- 托管 Edge 未登录初扫：`.runtime/exploration/2026-05-27T03-14-59-623Z-pdm-master-data-material-initial-pdm.megarobo.info.json`
- 缓存 PDM profile 成功初扫：`.runtime/exploration/2026-05-27T03-17-20-848Z-pdm-master-data-material-initial-cached-pdm.megarobo.info.json`
- 编码精确查询验证：`.runtime/pdm-results/2026-05-27T03-36-03-699Z-materialCode-4000059295.json`
- 名称模糊查询多页验证：`.runtime/pdm-results/2026-05-27T03-36-25-522Z-materialName-人力外包.json`

## 页面结构

筛选字段均为普通文本输入：

- `input[name="materialCode"]`：物料编码
- `input[name="materialName"]`：物料名称
- `input[name="specificationModel"]`：规格型号
- `input[name="materialGroupCode"]`：物料组编码
- `input[name="materialGroupDesc"]`：物料组描述
- `input[name="brand"]`：品牌
- `input[name="materialLevel"]`：物料等级

主要按钮：

- `搜 索`：提交筛选查询，安全。
- `重 置`：清空筛选条件，安全。
- 表格工具栏 `搜索`、`刷新`、`全屏`、`列设置`。
- 分页按钮包括 `首页`、`上一页`、页码、`下一页`、`末页`。

## 分页接口

页面自身触发的列表接口：

```text
GET https://pdm-api.megarobo.info/admin-api/master/data/material/page?pageNo=1&pageSize=20&materialCode=...
GET https://pdm-api.megarobo.info/admin-api/master/data/material/page?pageNo=1&pageSize=20&materialName=...
```

返回结构：

- `data.list`：当前页物料数组。
- `data.total`：命中总数。
- 默认 `pageSize=20`。

已确认的返回字段包括：

`id`、`materialCode`、`materialName`、`specificationModel`、`materialType`、`materialGroupCode`、`materialGroupDesc`、`machineType`、`materialDesc`、`unit`、`unitDesc`、`brand`、`brandCode`、`packaged`、`material`、`surfaceTreatment`、`transportationTemperature`、`productRecordNumber`、`materialLevel`、`supplierModelName`、`status`、`parameterDescription`、`enableGsp`、`productCompany`、`productLicenseNo`、`shippingUnit`、`freezeType`、`cbbFlag`、`keyAssemblyMaterialCode`、`keyTraceMaterialCode`、`keyAssemblyMaterialDesc`、`keyTraceMaterialDesc`。

## 固化脚本

脚本：`scripts/query-pdm.js`

Package script：

```powershell
npm.cmd run pdm:query
```

示例：

```powershell
npm.cmd run pdm:query -- --material-code 4000059295 --max-pages 2
npm.cmd run pdm:query -- --material-name "人力外包" --max-pages 2
npm.cmd run pdm:query -- --specification-model "18-5019" --max-pages 1
npm.cmd run pdm:query -- --material-group-code 407001 --max-pages 3
```

兼容旧用法：

```powershell
npm.cmd run pdm:query -- 4000059295
npm.cmd run pdm:query -- "传感器"
```

输出写入 `.runtime/pdm-results/*.json`，包含：

- `query.filters`：实际使用的筛选条件。
- `search.total`、`search.totalPages`、`search.fetchedPages`、`search.truncated`。
- `rows`：接口原始完整字段。
- `organizedRows`：按中文字段名整理后的结果。
- `materialResponses`：每页响应的 URL、页码、页大小、总数和行数据。

## 验证结果

- `--material-code 4000059295 --max-pages 2`：总数 1，读取 1 页，返回 `Octet链霉亲和素SA传感器`，规格 `18-5019`，单位 `盒`。
- `--material-name "人力外包" --max-pages 2`：总数 24，读取 2 页，返回 24 条，未截断。

## 维护注意

- 脚本通过页面输入和分页按钮触发 PDM 自己的 XHR，不直接读取或复用认证 token。
- `--material-code` 默认做精确后过滤；如需编码模糊或前缀查询，使用 `--material-code-like`。
- 默认最多读取 5 页；大范围模糊查询必须显式提高 `--max-pages`，避免误拉取超大结果集。
- 当前未固化 `状态` 下拉筛选；如需要启用/禁用过滤，应先补一次安全 interaction 探索下拉选项。
