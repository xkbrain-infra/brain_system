# BS-022 E2E 测试文档

## 概述

本文档描述 BS-022 IM 服务整合 Phase 2 的 E2E 测试覆盖范围。

## 测试覆盖

### 1. 双 Bot 消息收发完整链路
- **Telegram → telegram_api**: 通过 polling 接收消息
- **telegram_api → agent_gateway**: IPC 转发
- **agent_gateway → frontdesk**: 路由分发
- **Reply**: 反向链路验证

### 2. bots.yaml 热重载验证
- 修改 bots.yaml 后服务自动重载
- 新增/删除/修改 bot 配置正确处理
- 已运行 bot 不中断

### 3. 多 Bot 路由正确性
- bot_service_map 配置解析
- reply_targets 配置解析
- 双 bot 独立路由验证

## 测试文件

```
tests/
├── test_e2e_bs022.py      # E2E 主测试脚本
├── test_hot_reload.py     # 热重载单元测试
├── test_multi_bot.py      # 多 bot 配置测试
└── test_converter.py      # 消息转换测试
```

## 运行测试

```bash
# 进入 telegram_api 目录
cd /brain/infrastructure/service/telegram_api

# 运行 E2E 测试
PYTHONPATH=src python3 tests/test_e2e_bs022.py

# 运行所有测试
PYTHONPATH=src python3 -m pytest tests/ -v
```

## 测试结果

```
E2E Test Results: 8/8 passed
- bot_service_map parsing ✓
- reply_targets parsing ✓
- hot reload callback ✓
- bots.yaml structure ✓
- message flow Telegram→Gateway ✓
- reply flow Gateway→Telegram ✓
- both bots loaded ✓
- token env variables ✓
```

## 热重载机制

### telegram_api
- 使用 `watchdog` 库监听 bots.yaml
- 文件变化时触发 `_on_bots_reload` 回调
- 动态启动/停止 BotInstance

### brain_gateway
- 使用 `inotify` (Linux) 监听配置文件
- 变化时调用 `ReloadConfig()` 重新加载路由

## 配置说明

### bots.yaml 路径
`/brain/infrastructure/config/third_api/telegram/telegram.yaml`

### brain_gateway 配置
`/brain/infrastructure/service/brain_gateway/config/brain_gateway.json`
