# Session

- **Project**: brain_dashboard
- **Group**: brain
- **Path**: /xkagent_infra/groups/brain/projects/infrastructure/brain_dashboard
- **Sandbox Mode**: full_sandbox
- **Started**: 2026-03-15 10:30
- **Goal**: 升级 proxy 功能，精准显示所有流量流向（agent-to-agent flow visualization）

## Current Task

### Feature: Traffic Flow Visualization v2.0

**需求**: 从当前的粗略 inbound/outbound 统计，升级为精准的流量流向显示

**具体目标**:
1. 显示每条消息的具体流向（源 agent → 目标 agent）
2. 实时流量拓扑图数据
3. 请求链路追踪
4. 按 agent 分组统计

**相关文件**:
- `/src/api/v2/proxy.py` - 需要升级
- `/src/core/traffic_monitor.py` - 需要扩展

## Progress

- [x] Sandbox 评估 - full_sandbox 模式
- [x] 项目元数据创建
- [ ] 架构设计
- [ ] brain_gateway API 升级
- [ ] Dashboard proxy 模块升级
- [ ] 前端展示组件
- [ ] 测试验证
