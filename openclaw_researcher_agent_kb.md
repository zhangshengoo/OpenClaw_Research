# OpenClaw Researcher Assistant Framework — Agent 实现知识库

> 版本：v3.0 · 2026-03 · 基于源码深度分析 + 可行性评估修订
> 用途：后续实现 ASR 科研自动化 Agent 的权威参考

---

## 0. 核心认知前提

**OpenClaw 不是 Python 框架**，它是一个 **Node.js 个人 AI 助手 Gateway**，通过 WebSocket 控制平面（`ws://127.0.0.1:18789`）运行。

所有编排能力 **完全基于 OpenClaw 原生机制**，无需额外编排代码：

| 能力 | OpenClaw 机制 | 说明 |
|------|--------------|------|
| Agent 间编排 | `sessions_spawn` / `sessions_send` | 内置 Agent 间编排工具 |
| Agent 能力定义 | `workspace/skills/*/SKILL.md` | Gateway 启动时自动注入 |
| 状态持久化 | `state/*.json` 文件 | bash 读写，Gateway 重启不丢 |
| 模型路由 | `openclaw.json agents.list` | per-agentId 绑定不同模型，零代码配置 |
| 系统命令执行 | `bash tool (exec)` | Agent 直接调用 |
| 断点续跑 | Gateway daemon + `state/` 文件 | launchd/systemd 守护，天然持久 |
| 人工交互 | WebChat / Telegram / WhatsApp | 内置多渠道，零额外代码 |
| 实验隔离 | Python venv 隔离（不启用 Docker sandbox） | ⚠️ 不启用 sandbox，否则子 Agent 无法访问 state/ 文件 |

---

## 1. 系统架构

```
┌─────────────────────────────────────────────────┐
│  OpenClaw Gateway  ws://127.0.0.1:18789  Node.js│
├─────────────────────┬───────────────────────────┤
│  WebChat / Telegram │   Orchestrator (main)      │
│  内置多渠道          │   model: claude-opus-4-6   │
│  ◄─ human review ─► │   AGENTS.md + Skills 注入  │
│                     │   thinking: high (extended)│
└─────────────────────┴────────────┬──────────────┘
                      sessions_spawn × N（非阻塞，等 announce 回调）
          ┌──────────┬──────────┬──────────┬──────────┐
     Researcher   Planner    Coder     Critic    Reporter
    Sonnet 4.6  Opus 4.6  Sonnet 4.6 Opus 4.6 Sonnet 4.6
    (subagent)  (subagent)(subagent) (subagent)(subagent)
          └──────────┴────────── bash tool ──────────┘
                                   ▼
              ~/.openclaw/workspace/  (本地文件系统 · 纯 CPU)
              scripts/ · state/*.json · experiments/iter_N/
              data/chroma + mlflow
                                   ▼
                         Anthropic API + Voyage AI
```

**关键编排机制（Turn-Based 顺序编排）：**

1. `sessions_spawn` 是**非阻塞调用**，立即返回 `{status:"accepted", runId, childSessionKey}`
2. 子 Agent 完成后，Gateway 自动将 **announce 消息注入** Orchestrator 所在 channel，触发 Orchestrator **新一轮 turn**
3. Orchestrator 在新 turn 中读取 state/ 文件结果，然后 spawn 下一个子 Agent
4. 每个 PHASE **必须在独立 turn 中完成**——spawn 后当前 turn 结束，等 announce 到来再开始下一步

这是 **事件驱动的顺序编排**，不是在单个 turn 中写出完整 8 步流程。

---

## 2. 全局配置（openclaw.json）

```json5
// ~/.openclaw/openclaw.json
{
  agents: {
    defaults: {
      workspace: "~/.openclaw/workspace",
      subagents: {
        allowAgents: ["*"],           // ✅ 允许 spawn 任意 agentId（在 subagents 下）
        archiveAfterMinutes: 60,      // ✅ 默认 60 分钟，按需调大（框架文档写的 180 有误）
        maxConcurrent: 8,             // 全局并发子 Agent 上限
        runTimeoutSeconds: 1800,      // ✅ 设置全局默认超时（默认 0=不超时，必须显式设置）
      },
    },
    list: [
      {
        id: "main",                   // Orchestrator：Opus + extended thinking
        model:    "anthropic/claude-opus-4-6",
        thinking: { level: "high" },
      },
      {
        id: "researcher",             // 文献调研：Sonnet（高频抽取，成本敏感）
        model:    "anthropic/claude-sonnet-4-6",
        thinking: { level: "low" },
        // 子 Agent 默认无 sessions_spawn 权限，bash/read/write/exec 足够
        tools: {
          deny: ["browser", "canvas", "cron"],
        },
      },
      {
        id: "planner",                // 实验规划：Opus + thinking（深度推理）
        model:    "anthropic/claude-opus-4-6",
        thinking: { level: "high" },
        tools: { deny: ["browser", "canvas", "cron"] },
      },
      {
        id: "coder",                  // 代码生成：Sonnet（代码能力强，成本低）
        model:    "anthropic/claude-sonnet-4-6",
        thinking: { level: "medium" },
        tools: { deny: ["browser", "canvas", "cron"] },
      },
      {
        id: "critic",                 // 结果批判：Opus + thinking（深度 gap 分析）
        model:    "anthropic/claude-opus-4-6",
        thinking: { level: "high" },
        tools: { deny: ["browser", "canvas", "cron"] },
      },
      {
        id: "reporter",               // 报告生成：Sonnet（长文写作，成本敏感）
        model:    "anthropic/claude-sonnet-4-6",
        thinking: { level: "low" },
        tools: { deny: ["browser", "canvas", "cron"] },
      },
    ],
  },

  // ─── 人工交互渠道 ─────────────────────────────
  channels: {
    webchat:  { enabled: true },
    telegram: {
      enabled: true,
      botToken: "$TELEGRAM_BOT_TOKEN",
      dmPolicy: "allowlist",
      allowFrom: ["tg:YOUR_ID"],
    },
  },

  // ─── Sandbox 策略 ─────────────────────────────
  // ⚠️ 必须关闭 sandbox！默认 workspaceAccess:"none" 会创建隔离沙箱，
  //    子 Agent 将无法读写 state/ 文件，导致编排完全失败
  agents: {
    defaults: {
      sandbox: {
        mode: "off",              // ✅ 关键：关闭 sandbox，子 Agent 共享主 workspace
      },
    },
  },

  // ─── 子 Agent 工具策略（全局） ────────────────
  // ✅ 正确位置：tools.subagents.tools，不是顶层 sandbox.tools
  tools: {
    subagents: {
      tools: {
        deny: ["browser", "canvas", "cron", "discord"],
      },
    },
    exec: {
      timeout: 3600,              // ✅ 默认 1800s，ASR 实验需要 3600s
    },
  },
}
```

**配置关键修正：**
- **⚠️ sandbox 必须关闭**（`mode:"off"`）：默认 `workspaceAccess:"none"` 创建隔离沙箱 workspace，子 Agent 无法读写 `state/` 文件，编排失败。或者设置 `workspaceAccess:"rw"` 但更复杂
- `sandbox` **不是**顶层字段，应在 `agents.defaults.sandbox` 或 `agents.list[].sandbox`
- `allowAgents` 在 `agents.defaults.subagents.allowAgents`（不是 `agents.defaults.allowAgents`）
- `runTimeoutSeconds` 默认 **0（不超时）**，必须在 `agents.defaults.subagents.runTimeoutSeconds` 或每次 `sessions_spawn` 调用时显式设置
- 子 Agent 工具白名单通过 `tools.subagents.tools` 或 `agents.list[].tools` 配置
- **exec 超时默认 1800s**（不是 3600s），ASR 实验需显式设 `tools.exec.timeout: 3600`

**模型分工原则：**
- **Opus 4.6 + thinking=high**：Orchestrator、Planner（深度规划）、Critic（gap 分析）
- **Sonnet 4.6**：Researcher（高频抽取）、Coder（代码能力强）、Reporter（长文写作）
- **Haiku 4.5**：脚本内轻量调用（query 生成、错误摘要），非独立 Agent，~$0.001/次

---

## 3. 七步工作流（Pipeline）

```
STEP 01  需求解析      main session · Opus 4.6        结构化写入 state/current_task.json
STEP 02  文献调研      sessions_spawn researcher      非阻塞，等 announce 回调后读 survey.md
STEP 03  人工确认 ⏸   WebChat / Telegram             发综述摘要，等待"确认继续"（必须暂停）
STEP 04  实验规划      sessions_spawn planner         非阻塞，等 announce 回调后读 plan.yaml
STEP 05  代码生成      sessions_spawn coder           非阻塞，等 announce 回调确认写入完成
STEP 06  本地执行      bash tool 直接（不 spawn）      run_experiment.py · MLflow 追踪
STEP 07  批判迭代      sessions_spawn critic          非阻塞，等 announce 回调读 critic_N.json
收敛后   报告生成      sessions_spawn reporter        非阻塞，等 announce 回调发报告给用户
```

**收敛条件：** `critic_N.json.converged == true` 或 `iteration >= max_iter`

**announce 回调机制：**
- 子 Agent 完成后自动执行 announce 步骤，将结果发回 Orchestrator 所在 chat channel
- 子 Agent 回复 `ANNOUNCE_SKIP` → 静默宣告（不发消息）；Orchestrator 应通过 `bash` 读文件获取结果
- Orchestrator 在等待过程中可继续对话，announce 消息到来时触发下一步

---

## 4. Agent 设计详解

### 4.1 Orchestrator（main session）
- **模型：** Opus 4.6 · thinking=high
- **职责：** 接收用户需求 → sessions_spawn 子 Agent → bash 执行实验
- **注入文件：** `AGENTS.md` + `SOUL.md` + `USER.md` + `TOOLS.md`（主 session 完整注入）
- **关键：** 工作流逻辑全部写在 `AGENTS.md` 中，不写一行 Python 编排代码

### 4.2 Research Agent（researcher）
- **模型：** Sonnet 4.6 · thinking=low
- **职责：** bash 执行 `fetch_papers.py` → `embed_papers.py` → `generate_survey.py`
- **注入文件：** ⚠️ 仅 `AGENTS.md` + `TOOLS.md`（子 Agent 不注入 SOUL.md/USER.md/IDENTITY.md）
- **工具：** ArXiv API · Haiku 生成 query · Voyage-3.5 向量化 · ChromaDB

### 4.3 Planner Agent（planner）
- **模型：** Opus 4.6 · thinking=high
- **注入文件：** 仅 `AGENTS.md` + `TOOLS.md`
- **输入：** bash 读 `state/survey.md` + `state/current_task.json`
- **输出：** bash 写 `state/experiment_plan.yaml`（包含每轮超参数搜索空间、基线+改进+消融）

### 4.4 Coder Agent（coder）
- **模型：** Sonnet 4.6 · thinking=medium
- **注入文件：** 仅 `AGENTS.md` + `TOOLS.md`
- **输入：** bash 读 `state/experiment_plan.yaml`
- **输出：** bash 写 `experiments/iter_N/run.py` + `requirements.txt`
- **要求：** 必须输出标准化 `metrics.json` 接口

### 4.5 Critic Agent（critic）
- **模型：** Opus 4.6 · thinking=high
- **注入文件：** 仅 `AGENTS.md` + `TOOLS.md`
- **输入：** bash 读 `state/current_task.json` + 所有 `state/results_*.json`
- **输出：** bash 写 `state/critic_N.json`
  ```json
  {
    "converged": false,
    "improvements": [{"type": "...", "change": "...", "expected_gain": 0.02}],
    "gap_analysis": "..."
  }
  ```

### 4.6 Reporter Agent（reporter）
- **模型：** Sonnet 4.6 · thinking=low
- **注入文件：** 仅 `AGENTS.md` + `TOOLS.md`
- **输入：** bash 读 `survey.md` + 所有实验结果 + critic 分析
- **输出：** bash 写 `reports/final_report.md`（学术 Markdown 报告，含 MLflow 引用）

### 4.7 Haiku（脚本内隐式调用）
不作为独立子 Agent，在 Python 脚本内通过 Anthropic SDK 直接调用：
- `fetch_papers.py` 中生成 ArXiv query（~$0.001）
- `run_experiment.py` 中摘要 stderr 错误（~$0.001）
- JSON 格式化等高频轻量任务

---

## 5. Skills 系统（SKILL.md）

Skills 加载顺序（同名时 workspace 覆盖）：
1. Bundled（OpenClaw 内置）
2. `~/.openclaw/skills/`（全局 managed skills）
3. `<workspace>/skills/`（workspace 级，优先级最高）

**⚠️ 子 Agent 只注入 `AGENTS.md` + `TOOLS.md`**，SKILL.md 属于 workspace-level skills，同样会被注入（通过 workspace/skills 目录）。

| SKILL 名称 | 对应 Agent | 核心功能 |
|-----------|-----------|---------|
| `researcher-pipeline` | researcher | 4 步研究流水线：读任务→抓取→向量化→综述 |
| `experiment-runner` | main (Orchestrator) | venv 创建·MLflow 追踪·失败处理规范 |
| `voyage-embed` | researcher | Voyage API 规范：batch 限制·类型区分·ChromaDB schema |
| `critic-analyzer` | critic | 收敛判断·gap 分析框架·改进建议 JSON schema |
| `state-manager` | 所有 Agent 共享 | 统一状态 schema·迭代计数·历史聚合 |
| `asr-domain` | 所有 Agent 共享 | ASR 领域知识：CER/Recall@K/Latency P95·ArXiv 词库·推荐基线 |

**SKILL.md 格式示例：**
```markdown
---
name: researcher-pipeline
description: ASR文献调研流水线 - ArXiv抓取/向量化/综述生成
user-invocable: false
---

# Research Pipeline Skill
被 Orchestrator 通过 sessions_spawn 调用时，按以下顺序执行：

## Step 1: 读取任务定义
\`\`\`bash
cat ~/.openclaw/workspace/state/current_task.json
\`\`\`

## Step 2: 抓取论文
\`\`\`bash
python scripts/fetch_papers.py --task state/current_task.json --output state/papers.json
\`\`\`

完成后回复 ANNOUNCE_SKIP（Orchestrator 通过读 state/survey.md 获取结果）
```

---

## 6. AGENTS.md（Turn-Based 工作流设计）

`~/.openclaw/workspace/AGENTS.md` 是**所有 Agent（主+子）共享注入**的核心文件。
因此需要用 **角色条件段** 区分 Orchestrator 和子 Agent 的行为。

**⚠️ Turn-Based 编排核心原则：**
- `sessions_spawn` 非阻塞，调用后**当前 turn 必须结束**
- 子 Agent 完成后 announce 消息到来，触发 Orchestrator **新一轮 turn**
- 不能在单个 turn 中写出完整 8 步流程——每次 spawn 后停止，等下一个 turn

```markdown
# ASR Research Assistant

## 角色识别
- 如果你是 **main session**（Orchestrator），遵循下方「Orchestrator 工作流」
- 如果你被 **sessions_spawn 调用**（子 Agent），遵循下方「子 Agent 通用规范」

---

## Orchestrator 工作流（仅 main session）

你是 ASR 科研助手总编排者（claude-opus-4-6，extended thinking）。
编排采用 **Turn-Based 模式**：每次 spawn 后结束当前 turn，等 announce 回调再继续。

### 状态跟踪
每次 turn 开始时，先用 bash 读取 state/progress.json 确定当前 PHASE：
  bash: cat state/progress.json
如果文件不存在，从 PHASE 1 开始。

### PHASE 1 — 需求解析（当前 turn 完成）
将用户输入结构化，用 bash 工具写入：
  state/current_task.json  {query, tech_direction, target_metrics, max_iterations, min_delta}
  state/iteration.json     {current: 0, best_cer: 1.0, history: []}
  state/progress.json      {phase: 2, status: "spawning_researcher"}
然后立即进入 PHASE 2。

### PHASE 2 — 文献调研（spawn 后结束 turn）
sessions_spawn({
  agentId: "researcher",
  model: "anthropic/claude-sonnet-4-6",
  runTimeoutSeconds: 1200,
  task: "执行 researcher-pipeline SKILL 全部步骤，完成后回复 ANNOUNCE_SKIP"
})
用 bash 更新 state/progress.json: {phase: 2, status: "waiting_researcher"}
**⬛ 结束当前 turn，等待 announce 回调**

### [announce 到来 → 新 turn 开始]
用 bash 读取 state/survey.md 摘要发给用户，进入 PHASE 3。
更新 state/progress.json: {phase: 3, status: "waiting_human"}

### PHASE 3 — ✋ 人工确认（暂停等待用户消息）
等待用户回复"确认继续"。收到确认后进入 PHASE 4。

### PHASE 4 — 实验规划（spawn 后结束 turn）
sessions_spawn({
  agentId: "planner",
  model: "anthropic/claude-opus-4-6",
  runTimeoutSeconds: 600,
  task: "读取 state/current_task.json 和 state/survey.md，制定实验计划，
         写入 state/experiment_plan.yaml，完成后 ANNOUNCE_SKIP"
})
更新 state/progress.json: {phase: 4, status: "waiting_planner"}
**⬛ 结束当前 turn**

### [announce 到来 → 新 turn]
进入 PHASE 5。

### PHASE 5 — 代码生成（spawn 后结束 turn）
sessions_spawn({
  agentId: "coder",
  model: "anthropic/claude-sonnet-4-6",
  runTimeoutSeconds: 600,
  task: "读取 state/experiment_plan.yaml 当前迭代配置，
         生成 experiments/iter_${ITER}/run.py + requirements.txt，
         确保输出 metrics.json，完成后 ANNOUNCE_SKIP"
})
更新 state/progress.json: {phase: 5, status: "waiting_coder"}
**⬛ 结束当前 turn**

### [announce 到来 → 新 turn]
进入 PHASE 6。

### PHASE 6 — 本地执行（bash 直接调用，不 spawn）
bash 执行实验（在当前 turn 中完成）：
  cd ~/.openclaw/workspace && source venv/bin/activate
  ITER=$(python3 -c "import json; print(json.load(open('state/iteration.json'))['current'])")
  timeout 3600 python scripts/run_experiment.py \
    --config state/experiment_plan.yaml --iter $ITER --output state/results_${ITER}.json
执行完成后直接进入 PHASE 7（无需新 turn）。

### PHASE 7 — 批判判断（spawn 后结束 turn）
sessions_spawn({
  agentId: "critic",
  model: "anthropic/claude-opus-4-6",
  runTimeoutSeconds: 600,
  task: "读取 state/current_task.json 和所有 state/results_*.json，
         分析 gap，输出 state/critic_${ITER}.json:
         {converged:bool, improvements:[], gap_analysis:str}
         完成后 ANNOUNCE_SKIP"
})
更新 state/progress.json: {phase: 7, status: "waiting_critic"}
**⬛ 结束当前 turn**

### [announce 到来 → 新 turn]
bash 读取 state/critic_${ITER}.json：
- converged=false 且 current < max_iterations → 更新 iteration.json，回到 PHASE 4
- converged=true 或到达上限 → 进入 PHASE 8

### PHASE 8 — 报告生成（spawn 后结束 turn）
sessions_spawn({
  agentId: "reporter",
  model: "anthropic/claude-sonnet-4-6",
  runTimeoutSeconds: 600,
  task: "读取 survey.md + 所有实验结果 + critic 分析，
         生成 reports/final_report.md，完成后 ANNOUNCE_SKIP"
})
**⬛ 结束当前 turn**

### [announce 到来 → 最终 turn]
bash 读取 reports/final_report.md 发给用户。流程完成。

---

## 子 Agent 通用规范（被 spawn 调用时）

1. 你的 task 参数包含具体指令，按指令执行
2. 所有输入数据通过 bash 从 state/ 目录读取
3. 所有输出结果通过 bash 写入 state/ 目录
4. **不要**尝试调用 sessions_spawn 或 sessions_send（你没有权限）
5. 完成后回复 ANNOUNCE_SKIP（Orchestrator 通过读文件获取结果）
6. 如果遇到错误，将错误信息写入 state/error.json 并回复 ANNOUNCE_SKIP

## 状态规范
全部中间结果通过 bash 读写 ~/.openclaw/workspace/state/ 文件。
子 Agent 之间不通过 LLM 上下文传递数据，避免上下文膨胀。
新增 state/progress.json 跟踪当前 PHASE，支持断点续跑。
```

---

## 7. Python 脚本层

Python 脚本是被 bash tool 调用的**纯计算层**，不做任何编排。

### 7.1 fetch_papers.py（ArXiv 抓取）
```python
# Haiku 生成 3-5 个 ArXiv query（~$0.001）
# Sonnet 抽取方法/数据集/指标，并打相关性分 0-10
# 过滤 relevance >= 6 的高相关论文
# 输出: state/papers.json
```

### 7.2 embed_papers.py（向量化）
```python
# voyage-3.5 · input_type="document" · batch=64
# ChromaDB PersistentClient → ~/.openclaw/workspace/data/chroma
# upsert(ids, embeddings, documents, metadatas)
```

### 7.3 generate_survey.py（RAG 综述）
```python
# 用 tech_direction 生成 query embedding（input_type="query"）
# ChromaDB 检索 top_k=12
# Sonnet 生成 3000 字综述（方法对比/指标/基线/建议）
# 输出: state/survey.md
```

### 7.4 run_experiment.py（本地执行）
```python
# 读取 experiment_plan.yaml[iterations][iter]
# 创建隔离 venv + 安装 requirements.txt
# MLflow 追踪（log_params, log_metrics）
# subprocess.run(venv/bin/python run.py, timeout=3600)
# 失败时 Haiku 摘要 stderr（~$0.001）
# 读取 experiments/iter_N/metrics.json 输出结果
```

---

## 8. 状态管理（文件系统持久化）

**核心设计：** 所有 Agent 间状态通过文件共享，不通过 LLM 上下文传递，避免上下文膨胀。

| 文件 | 写入方 | 读取方 |
|------|--------|--------|
| `state/progress.json` | Orchestrator（每个 PHASE 更新） | Orchestrator（每个 turn 开始时读取，断点续跑） |
| `state/current_task.json` | Orchestrator (PHASE 1) | 所有子 Agent（通过 bash） |
| `state/papers.json` | fetch_papers.py | embed_papers.py · generate_survey.py |
| `state/survey.md` | generate_survey.py | Orchestrator · Planner · Reporter（通过 bash） |
| `state/experiment_plan.yaml` | Planner Agent（通过 bash） | Coder · run_experiment.py |
| `state/iteration.json` | Orchestrator（每轮更新） | 所有 Agent（通过 bash） |
| `state/results_N.json` | run_experiment.py | Critic · Reporter |
| `state/critic_N.json` | Critic Agent（通过 bash） | Orchestrator（收敛判断） |
| `reports/final_report.md` | Reporter Agent（通过 bash） | Orchestrator（发给用户） |

### current_task.json Schema
```json
{
  "query": "研究问题描述",
  "tech_direction": "技术方向",
  "target_metrics": {"cer": 0.08, "latency_p95_ms": 50, "recall_10": 0.90},
  "max_iterations": 6,
  "min_delta": 0.005
}
```

---

## 9. workspace 目录结构

```
~/.openclaw/workspace/
├── AGENTS.md                        # Orchestrator 系统提示 + 核心工作流定义（主+子 Agent 均注入）
├── SOUL.md                          # 助手人格（仅主 session 注入，子 Agent 不注入）
├── TOOLS.md                         # 工具使用说明（主+子 Agent 均注入）
├── USER.md                          # 用户信息（仅主 session 注入）
├── skills/
│   ├── researcher-pipeline/SKILL.md
│   ├── experiment-runner/SKILL.md
│   ├── voyage-embed/SKILL.md
│   ├── critic-analyzer/SKILL.md
│   ├── state-manager/SKILL.md
│   └── asr-domain/SKILL.md
├── scripts/
│   ├── fetch_papers.py              # arxiv + Haiku + Sonnet
│   ├── embed_papers.py             # Voyage voyage-3.5 + ChromaDB
│   ├── generate_survey.py          # RAG + Sonnet 综述
│   ├── run_experiment.py           # venv + subprocess + MLflow + Haiku
│   └── requirements.txt            # anthropic voyageai chromadb mlflow arxiv pypdf2 pyyaml
├── state/                           # 所有 Agent 间共享状态（bash 读写）
│   ├── current_task.json
│   ├── progress.json               # Turn-Based 断点续跑状态（当前 PHASE + status）
│   ├── papers.json
│   ├── survey.md
│   ├── experiment_plan.yaml
│   ├── iteration.json
│   ├── results_N.json              # 每轮实验结果
│   ├── critic_N.json               # 每轮批判结果
│   └── error.json                  # 子 Agent 错误信息（可选）
├── experiments/
│   └── iter_N/
│       ├── run.py
│       ├── requirements.txt
│       ├── metrics.json            # 标准化输出接口
│       └── venv/
├── data/
│   ├── chroma/                     # ChromaDB 本地向量库
│   └── mlflow/                     # MLflow SQLite 实验追踪
└── reports/
    └── final_report.md
```

**注：** `~/.openclaw/openclaw.json`、`~/.openclaw/credentials/`、`~/.openclaw/agents/*/sessions/` **不在 workspace 中**，不要混淆。

---

## 10. sessions_spawn 调用规范

```javascript
// ✅ 正确调用模式
sessions_spawn({
  agentId: "researcher",                    // 对应 openclaw.json agents.list 中的 id
  model:   "anthropic/claude-sonnet-4-6",   // 可覆盖默认模型
  label:   "research-phase",               // 可选标签（用于日志/UI）
  runTimeoutSeconds: 1200,                  // ⚠️ 必须显式设置！默认 0=不超时
  task:    `执行 researcher-pipeline SKILL 全部步骤。完成后回复 ANNOUNCE_SKIP`
})
// 立即返回 { status: "accepted", runId, childSessionKey }
// 子 Agent 完成后，announce 消息回传 Orchestrator 所在 chat channel
```

**关键行为说明：**

| 行为 | 说明 |
|------|------|
| 非阻塞 | `sessions_spawn` 立即返回，不等待子 Agent 完成 |
| announce 回调 | 子 Agent 完成后自动发 announce 消息给 Orchestrator 所在 channel |
| `ANNOUNCE_SKIP` | 子 Agent 回复此字符串 → 静默不发消息；Orchestrator 应 bash 读文件获结果 |
| 子 Agent 无 spawn 权限 | 默认 `maxSpawnDepth=1`，子 Agent **不能**再 spawn 子 Agent |
| task 简洁原则 | task 只传简短指令，大数据通过 bash 读 state/ 文件（防止 task 携带大量文本） |
| 子 Agent 上下文 | 只注入 `AGENTS.md` + `TOOLS.md`，不注入 SOUL.md/USER.md/IDENTITY.md |
| 自动归档 | 子 Agent session 在 `archiveAfterMinutes`（默认 60）分钟后自动归档 |

---

## 11. 费用估算（6轮完整迭代）

| 组件 | 模型 | 费用/次 |
|------|------|---------|
| Orchestrator | Opus 4.6 | ~$0.6 |
| Research Agent | Sonnet 4.6 | ~$0.8 |
| Planner Agent | Opus 4.6 | ~$0.5 |
| Coder Agent ×6 | Sonnet 4.6 | ~$1.2 |
| Critic Agent ×6 | Opus 4.6 | ~$1.6 |
| Reporter | Sonnet 4.6 | ~$0.4 |
| Haiku（脚本内）| Haiku 4.5 | ~$0.05 |
| Voyage Embedding | voyage-3.5 | ~$0.05 |
| **总计** | | **$4–6/次** |

**成本优化：** Critic 首轮可用 Sonnet，稳定后升 Opus；Anthropic Console 设月度预算告警。

---

## 12. 风险与应对

| 风险 | 等级 | 应对策略 |
|------|------|---------|
| Agent 代码幻觉 | 高 | bash 捕获 stderr，Haiku 摘要错误 → Critic 自动诊断；per-agent tools.deny 限制危险工具 |
| 无限迭代循环 | 高 | AGENTS.md 写明硬限制；iteration.json 计数；`runTimeoutSeconds` 兜底（必须显式设置） |
| 上下文爆炸 | 中 | task 只传简短指令；所有大数据通过 bash 读 state/ 文件 |
| 实验不可复现 | 中 | MLflow 记录参数/指标；venv pin 版本；random seed 写入 config |
| API 费用失控 | 中 | Critic 降级 Sonnet；设月度预算告警；maxConcurrent 控制并发 |
| sandbox 隔离导致状态不可见 | **极高** | ⚠️ 必须 `sandbox.mode:"off"`；否则子 Agent 在隔离沙箱 workspace 中，无法读写 `state/` 文件 |
| exec 超时不足 | 高 | 默认 exec timeout 1800s，ASR 实验可能超时；必须显式设 `tools.exec.timeout: 3600` |
| turn 排序错乱 | 中 | Orchestrator 在单 turn 中连续 spawn 多个 Agent 会导致并发冲突；严格按 Turn-Based 模式，每次只 spawn 一个 |
| AGENTS.md 对子 Agent 浪费 token | 低 | 所有 Agent 共享同一 AGENTS.md，子 Agent 会读到 Orchestrator 的 PHASE 定义；通过角色条件段减少混淆 |
| Gateway 崩溃 | 低 | --install-daemon 守护；state/ 持久化 + progress.json，重启后读 progress.json 续跑 |
| announce 丢失 | 低 | Gateway 重启会丢失 pending announce；备用方案：Orchestrator 轮询 sessions_history |

---

## 13. 安装启动命令

```bash
# 1. 安装 OpenClaw（Node.js ≥22）
npm install -g openclaw@latest
openclaw onboard --install-daemon      # 配置向导 + launchd/systemd 守护进程

# 2. Python 环境（CPU only，零 GPU）
cd ~/.openclaw/workspace
python3 -m venv venv && source venv/bin/activate
pip install anthropic voyageai chromadb mlflow arxiv pypdf2 pyyaml

# 3. 环境变量（bash tool 继承）
echo 'export ANTHROPIC_API_KEY="sk-ant-..."' >> ~/.zshrc
echo 'export VOYAGE_API_KEY="pa-..."'        >> ~/.zshrc
source ~/.zshrc

# 4. 创建 Skills 目录和文件
mkdir -p skills/{researcher-pipeline,experiment-runner,voyage-embed,critic-analyzer,state-manager,asr-domain}
# 将各 SKILL.md 内容写入对应目录

# 5. 启动 Gateway
openclaw gateway run --port 18789 --verbose
# WebChat: http://127.0.0.1:18789

# 6. 发送第一条研究请求
openclaw agent --thinking high \
  --message "需求: 大规模热词召回替代GLCLAP。方向: Dual-Encoder+FAISS音文对齐。目标CER≤0.08，延迟P95≤50ms，词库10k+，最多6轮迭代"

# 7. 查看实验追踪
mlflow ui --backend-store-uri ~/.openclaw/workspace/data/mlflow --port 5000

# 8. 查看子 Agent 状态
# /subagents list     → 列出当前 session 的所有子 Agent
# /subagents log <id> → 查看子 Agent 日志
# /subagents kill all → 停止所有子 Agent
```

---

## 14. ASR 领域知识（asr-domain SKILL）

**目标指标：**
- CER（字符错误率）≤ 0.08
- Latency P95 ≤ 50ms
- Recall@10 ≥ 0.90
- 热词词库规模：10k+

**推荐基线：**
- DualEncoder（音文对齐）
- CIF-biasing（CIF 热词偏置）
- TCPGen（Tree Constrained Pointer Generator）

**关键技术方向：** AudioEncoder + LLM · FAISS 检索 · 热词召回

---

## 15. 关键设计原则（实现 Agent 时务必遵守）

1. **Turn-Based 编排**：每次 spawn 后结束当前 turn，等 announce 到来触发新 turn 再继续——**不能在单 turn 中写完整流程**
2. **sandbox 必须关闭**：`agents.defaults.sandbox.mode: "off"`，否则子 Agent 在隔离 workspace 中无法读写 state/
3. **编排逻辑在 AGENTS.md/SKILL.md，不在 Python 代码中**
4. **Agent 间通信通过文件系统，不通过 LLM 上下文**（防上下文爆炸）
5. **子 Agent task 只传简短指令**，大数据 bash 读 state/ 文件
6. **本地执行不 spawn 子 Agent**，Orchestrator 直接 bash 调用
7. **Haiku 不作为独立 Agent**，在脚本内 SDK 调用高频轻量任务
8. **每轮实验完全隔离**，独立 venv + 独立 experiments/iter_N/ 目录
9. **MLflow 追踪所有实验**，params/metrics/artifacts 全部记录
10. **人工审查检查点**（PHASE 3）必须暂停，等待用户确认
11. **`runTimeoutSeconds` 必须显式设置**，默认 0=不超时，建议 subagents 全局设 1800
12. **exec 超时必须显式设 3600**，默认仅 1800s，ASR 实验不够用
13. **Gateway 作为 daemon** 运行，state/ + progress.json 保证断点续跑
14. **子 Agent 不能再 spawn 子 Agent**（默认 `maxSpawnDepth=1`，只有 main 可 spawn）
15. **子 Agent 只注入 AGENTS.md + TOOLS.md**，SOUL.md/USER.md 等不注入
16. **AGENTS.md 使用角色条件段**，区分 Orchestrator 和子 Agent 行为，减少 token 浪费

---

## 附录 A：源码核实的主要差异（v2.1 修正，相比框架设计文档 v4）

| 设计文档说法 | 源码实际行为 | 修正方向 |
|------------|-------------|---------|
| `sandbox: { mode:"non-main", tools:{...} }` 在顶层 | `sandbox` 应在 `agents.defaults.sandbox` 或 `agents.list[].sandbox`；工具策略在 `tools.subagents.tools` 或 `agents.list[].tools` | 配置结构调整 |
| `subagents.archiveAfterMinutes: 180` | 默认值为 **60** | 改为 60，或显式设置 |
| `runTimeoutSeconds` 有默认值 | 默认 **0（不超时）**，必须显式设置 | 每次 spawn 或全局设置 |
| 子 Agent 可继续 spawn 子 Agent | 默认 `maxSpawnDepth=1`，**子 Agent 禁止 spawn**，需设 `maxSpawnDepth: 2` 才可嵌套 | 本框架 Orchestrator 是 main，不受限；子 Agent（researcher/coder 等）不能再 spawn |
| `ANNOUNCE_SKIP` 是"完成信号" | `ANNOUNCE_SKIP` 是"静默宣告"，用于不发消息；完成由 announce 步骤自动触发 | 语义区分 |
| 子 Agent 注入完整 workspace 文件 | **只注入 `AGENTS.md` + `TOOLS.md`**，SOUL.md/USER.md/IDENTITY.md 等不注入 | SKILL.md 的指令写到对应 agent 的 AGENTS.md 或 skill 文件中 |
| `sessions_spawn` 阻塞等待 | **完全非阻塞**，立即返回，通过 announce 回调通知完成 | Orchestrator 需要等待 announce 消息再进行下一步 |

---

## 附录 B：可行性评估关键发现（v3.0 新增）

### 三大架构调整（必须执行）

| # | 问题 | 根因 | 修正 |
|---|------|------|------|
| 1 | 子 Agent 无法读写 state/ 文件 | sandbox 默认 `workspaceAccess:"none"` 创建隔离 workspace | `agents.defaults.sandbox.mode: "off"` 关闭 sandbox |
| 2 | AGENTS.md 设计为单 turn 线性流程 | `sessions_spawn` 非阻塞，spawn 后 turn 结束 | 改为 Turn-Based 设计：每 PHASE 一个 turn，spawn 后结束等 announce |
| 3 | exec 超时不足 | 默认 1800s（源码 `DEFAULT_EXEC_TIMEOUT=1800`） | 显式设 `tools.exec.timeout: 3600` |

### 源码验证的关键行为

| 行为 | 源码位置 | 详情 |
|------|---------|------|
| spawn 非阻塞 | `subagent-spawn.ts` | 立即返回 `{status:"accepted"}`，不等子 Agent 完成 |
| announce 推送 | `subagent-announce.ts` | 完成后通过 `agent.wait` RPC 推送到 Orchestrator channel |
| 持久化注册 | `subagent-registry.ts` | `~/.openclaw/subagents/runs.json`，Gateway 重启后 3 次重试恢复 |
| 模型路由 | `model-selection.ts` | spawn.model > agent.subagents.model > defaults.subagents.model > agent.model > defaults.model |
| exec 输出限制 | `bash-tools.exec-runtime.ts` | `DEFAULT_MAX_OUTPUT=200KB`，超出截断；timeout 默认 1800s |
| workspace 共享 | `agent-workspace.md` | sandbox off 时子 Agent 与主 Agent 共享同一 workspace，state/ 可直接读写 |
| 无文件锁 | 全局 | OpenClaw 无内置文件锁；Turn-Based 编排保证单写者（sequential），安全 |
| Skill 加载 | `workspace.ts` | workspace/skills/ 优先级最高，覆盖 managed 和 bundled skills |
