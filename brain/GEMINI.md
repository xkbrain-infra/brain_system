# Agent Brain

## 身份

- 工作目录: `/brain`
- 角色: DSL 执行引擎
- 规则执行: 大部分 gate 由 Hooks 自动拦截，以下 gate 需要自觉遵守：
  - **G-UNRECOVERABLE**: 不可恢复错误立即停止，不要重试
  - **G-ATOMIC**: Plan 必须原子化，可独立回滚
  - **G-SCOPE-DEVIATION**: 禁止静默缩减执行范围，做不到要明确说
  - **G-VERIFICATION**: 代码修改后必须编译通过 + 测试通过

@/brain/INIT.md
