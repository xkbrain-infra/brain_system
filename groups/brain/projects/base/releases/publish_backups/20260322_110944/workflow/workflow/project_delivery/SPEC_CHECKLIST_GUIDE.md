# Spec Checklist Guide

给执行 `project_delivery` workflow 的 agent 用。先区分两件事：

- `SPEC_CHECKLIST.yaml`
  workflow 自带的标准 list，定义一次完整执行至少要做多少项
- `project_root/spec/spec_checklist.yaml`
  某个具体项目对这份标准 list 的执行实例

不要把这两者混在一起。

## 你要做什么

1. 先读取 `SPEC_CHECKLIST.yaml`，确认这次 workflow 的标准总项数
2. 在 planning 阶段初始化 `project_root/spec/spec_checklist.yaml`
3. 先把全部 base items 原样实例化
4. 再补项目特有的 extension items
5. 把 workflow steps、pass gate、deliverables、milestones、validation path 映射成 checklist item
6. 给每个 item 写清楚：
   - `source_ref`
   - `severity`
   - `completion_rule`
   - `required_evidence`
   - `owner`
   - `status`
   - `evidence_policy`
7. 在 task modeling 阶段把 item 映射到 task、milestone 或 validation path
8. 在 execution/release 阶段持续回写 `status` 和 `evidence_refs`
9. 在 audit 阶段检查漏项、伪完成、缺证据完成、未经审批的 waive

## 你不能怎么做

- 不能只写“阶段完成”，不写 checklist item
- 不能跳过 `SPEC_CHECKLIST.yaml` 自己发明总项数
- 不能因为赶时间直接删 item
- 不能把 base items 改成可选项
- 不能把 task done 直接等同于 checklist done
- 不能没有 evidence 就把 required item 标成 done
- 不能没有 `waived_by` 和 `waive_reason` 就标记 `waived`

## 最小操作顺序

1. 读 `SPEC_CHECKLIST.yaml`
2. 读 `contracts/spec_checklist_contract.yaml`
3. 复制 `spec_checklist.instance.template.yaml` 到 `project_root/spec/spec_checklist.yaml`
4. 生成项目 checklist baseline
5. 统计 `base_items` / `extension_items` / `total_items`
6. 优先检查 `critical` items 是否都有 owner 和 evidence path
7. 每次 task/review/test/release 有关键进展时同步 checklist
8. 出 delivery_report 时带上 checklist summary
9. 出 audit_report 时带上 coverage assessment

## 完成判断

项目“完成度”至少要能回答下面 4 个问题：

- 标准 base list 一共多少个点
- 已完成多少个
- 哪些点被 block 或 waive
- 每个已完成点的 evidence 在哪里

如果这 4 个问题答不出来，就不要声称项目完成度清楚。
