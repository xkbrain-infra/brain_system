---
id: G-SKILL-DOC-SEARCH
name: doc-search
description: "This skill should be used when the user asks to \"查文档\", \"查规范\", \"查 ipc\", \"doc_search\", \"在系统已有文档里找\", or when questions target Brain existing docs and policy lookup."
user-invocable: true
disable-model-invocation: false
allowed-tools: doc_search, Read
argument-hint: "[query] [--limit N]"
---

# doc-search — 先召回再精读

目标：先用向量检索缩小范围，再定点读取，降低 token 消耗并保持结论准确。

## 默认流程

1. 先执行 `doc_search(query, limit=10)` 做语义召回。
2. 选 Top-K 文档（默认 K=3，最多 K=5）。
3. 仅对 Top-K 做定点读取（标题、规则段、参数段、验收段）。
4. 输出时区分：
   - `Search hits`（召回结果）
   - `Verified facts`（已读取原文确认）
   - `Inference`（基于多文档推断）

## 触发策略

以下场景默认启用本技能：
- 用户明确说“用 doc_search 查 ...”。
- 问题是 Brain 内部规范/流程/gate/策略定位。
- 需要先判断“哪份文档是权威来源”。

## Fallback 规则

当出现以下情况时，不能只停留在检索结果：
- Top1 相似度低（< 0.45）或结果明显分散。
- 问题涉及精确参数（阈值、重试次数、路径、版本）。
- 存在互相冲突的候选文档。

执行：
1. 改写 query 再次 `doc_search`（可加域词：`spec`/`workflow`/`knowledge`）。
2. 使用 registry quick_lookup 定位官方文档 ID。
3. 读取对应原文进行最终确认。

## 输出模板

- `Top hits`: 列出 `id / path / similarity`。
- `Confirmed`: 只写已回源验证过的结论。
- `Next read (optional)`: 若结论仍不完整，给出下一步要读的 1-2 个文档。

## 边界

- `doc_search` 用于“定位”，不是最终事实来源。
- 高风险结论（执行命令、配置修改、删除/重启）必须回源原文后再给建议。
