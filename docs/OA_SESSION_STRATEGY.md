# OA 登录态策略

OA 入口统一为：

```text
https://oa.megarobo.info/wui/index.html?#/main/portal/portal-1-1?menuIds=0,1&menuPathIds=0,1&_key=tcagna
```

## 当前判断

如果 OA 在普通 Edge 中登录后，一旦关闭 Edge 再打开就提示登录超时，说明 OA 很可能使用浏览器会话 Cookie 或服务端短会话。此时复制已关闭的 Edge Profile 无法可靠保留 OA 登录态。

PDM 可以通过 Profile 缓存复用，是因为它的登录态会持久化到浏览器 Profile 中。OA 和 PDM 可以共用同一套缓存脚本，但 OA 的结果取决于 OA 是否提供可持久化登录态。

## 正确方案

### 方案 A：缓存 Profile

适合 PDM，以及任何关闭浏览器后仍保持登录的系统。

流程：

1. 用户在普通 Edge 登录。
2. 关闭 Edge。
3. 执行 A 缓存 Profile。
4. 执行 B 测试登录态。

### 方案 B：工具托管活会话

适合 OA 这类关闭浏览器就失效的系统。

流程：

1. 工具启动 Playwright Edge。
2. 用户在这个 Edge 窗口内扫码登录 OA。
3. 不关闭该 Edge/不重启工具服务。
4. 后续 OA 自动化都在同一个运行中的浏览器上下文中完成。

## 诊断

前端按钮“诊断 OA 会话”会打开 OA portal，返回 cookie 名称、域名和过期属性，但不返回 cookie 值。

`expires = -1` 表示浏览器会话 Cookie；如果 OA 相关 cookie 全是这种类型，关闭 Edge 后重新登录就是预期行为。
