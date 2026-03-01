# How to Use Agent Brain with Claude Code

So you've cloned `agent_brain` to a new machine. How do you "plug it in"?

## 1. The Principle: "Context Injection"

Agents (like Claude Code, Cursor, Windsurf) don't automatically "know" everything in the repo. You must **feed** the relevant parts of the Brain into their context window.

## 2. 🛰 Remote Assistant Connection (Telepresence)

To enable the AI Assistant (Antigravity/Claude Code) to operate natively inside the `xnas` environment, use the **Remote-SSH** method.

### 1. SSH Configuration
Add the following to your local `~/.ssh/config` on your workstation:

```ssh
Host xnas-ai-core
    HostName xnas-ubuntu-ts.717182.xyz
    Port 8422
    User root
```

### 2. IDE Connection (VS Code / Cursor)
1. Install the **Remote - SSH** extension.
2. Click the Remote icon -> **Connect to Host...** -> **xnas-ai-core**.
3. Open the folder: `/app/agent_workspace`.
4. **Result**: The AI Assistant now executes tools (`rg`, `docker`, `npm`) directly within the `xnas` container.

### 3. Port Mapping Reference
- **Dashboard (Frontend)**: `http://<xnas-ip>:8401`
- **Backend API**: `http://<xnas-ip>:8400`
- **SSH (Container)**: `8422`

## 3. Usage Patterns

### Pattern A: The "Kickoff" (Start of Session)
When you start a new chat or session, tell the Agent **who** it is and **what** rules to follow.

**Prompt Example**:
> "Hi. Please read `base/prompts/roles/architect.md` and adopt that persona. Also review `base/spec/coding_standards.md` because I need you to write some code compliant with our team rules."

### Pattern B: The "Project Context" (Working on specific project)
When working on *Silk Road*, point the Agent to the *Group* level spec.

**Prompt Example**:
> "I'm working on the Silk Road project. Read `groups/commerce_group/README.md` to understand the workflow, and check `groups/commerce_group/projects/silk_road/spec/brand_strategy.md` for context."

## 3. Persistence (How to make it "Stick")

To avoid copying and pasting every time, we use **Rules Files**.

### For All AI Tools (Multi-Bot Support)
We have provided standard transition files to ensure all major Agents recognize this Brain:
-   **`.clauderules`**: For Claude Code.
-   **`.cursorrules`**: For Cursor & **Gemini-based** plugins.
-   **`.codexrules`**: For Codex-based tools.
-   **`.windsurfrules`**: For Windsurf.

These files are synchronized (copies of each other) to ensure the **6 Pillars** are respected regardless of which tool you open.

## 4. Quick Start Prompts (Copy & Paste)

Here are some "Magic Spells" you can paste directly to Claude:

### 🧙‍♂️ Summon Architect (Infrastructure Mode)
> "Please read `base/prompts/roles/architect.md` and `base/spec/coding_standards.md`. I need you to act as the System Architect to review my current codebase structure."

### 🛍️ Summon E-commerce Strategist (Silk Road Mode)
> "Please read `groups/commerce_group/prompts/roles/ecom_strategist.md` and `groups/commerce_group/projects/silk_road/workflow.md`. I am ready to start the 'Observe' phase for the Silk Road project."

### 🤖 Summon Automation Engineer (n8n Mode)
> "Please read `groups/automation_group/spec/deployment.md` and `groups/automation_group/mcp/n8n.json`. I need help debugging my docker-compose setup."

## 5. Tool Configuration (MCP)

For tools (MCP Servers) to work, you need to configure your client.

-   **Claude Desktop**: Copy the content of `base/mcp/*.json` into your `claude_desktop_config.json`.
-   **Cursor / VSCode**: Some extensions allow defining 'Instruction Files' (e.g., `.cursorrules`). You can copy the content of `base/prompts/system/core_instructions.md` into `.cursorrules` to make it permanent.
