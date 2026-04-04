# 🧠 Agent Brain: 神经中枢 (Central Command)

**Agent Brain** 是 AI Agent 的分布式操作系统与决策中枢。它定义了 Agent 的思考方式、行为准则和记忆结构。

## 🚀 启动入口 (Bootloader)

**`INIT.md` 是系统的唯一入口。**
任何 Agent 在接管本仓库时，必须优先读取并执行 [INIT.md](./INIT.md)。它负责：
1.  **身份加载**：确认 Agent 的权限与职责。
2.  **内核挂载**：加载 `base/` 下的核心协议（如 LEP，权威路径：`/brain/base/spec/policies/lep/lep.yaml`）。
3.  **记忆同步**：连接 Memory 2.0 系统。

---

## 🏗️ 系统架构 (Architecture)

本系统采用 **Base -> Group -> Project** 的三层继承架构：

### 1. 核心基座 (Base) - `/brain/base`
这是系统的内核，定义了所有 Agent 必须遵循的 **七大支柱 (The 7 Pillars)**：

*   **📜 规范 (spec)**：系统的“宪法”。定义了 LEP 协议、编码标准和工作流。
*   **🛠️ 技能 (Skills)**：系统的“双手”。可复用的工具脚本和操作指南。
*   **🔌 连接 (MCP)**：系统的“神经”。Model Context Protocol 配置，用于连接外部世界。
*   **🎭 人设 (Prompts)**：系统的“灵魂”。定义了 Agent 在不同场景下的角色（如架构师、工程师）。  
*   **📚 知识 (Knowledge)**：系统的“大脑皮层”（冷存储/参考书）。
    *   *定义*：静态的、经过验证的知识库。
    *   *用途*：存储解决方案、技术手册、最佳实践和“如何做”的指南。**Agent 在遇到未知问题或需要查阅标准做法时，应将其视为“查询手册”进行检索。**
*   **🧩 记忆 (Memory)**：系统的“海马体”（热存储/工作台）。
    *   *定义*：动态的运行时状态。
    *   *用途*：Memory 2.0 架构，记录当前任务状态、审计日志 (Logs) 和每日快照 (State)。它是你工作的“现场”。
*   **🧪 评估 (Evals)**：系统的“免疫系统”。用于能力测试和质量门控。

### 2. 业务组织 (Groups) - `/brain/groups`
基于 `base` 衍生出的具体业务单元。每个 Group 继承 Base 的能力，并根据特定领域进行特化。

*   **[brain_system_group](./groups/brain_system_group)**: 元系统维护与自进化。
*   **[xkquant_group](./groups/xkquant_group)**: 量化交易与工程研发。
*   **[commerce_group](./groups/commerce_group)**: 商业咨询与市场分析。
*   **[automation_group](./groups/automation_group)**: 自动化工作流服务。

### 3. 项目实例 (Projects) - `/brain/groups/{group}/projects/{project}`
最小执行单元。具体的任务在此执行，拥有独立的 `memory` 上下文。

---

## 📖 快速开始

1. **初始化**：阅读 [INIT.md](./INIT.md)。
2. **学习内核**：深入阅读 [Base README](./base/README.md)。
3. **选择任务**：进入具体的 Group 或 Project 目录开始工作。
