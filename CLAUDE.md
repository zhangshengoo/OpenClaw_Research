# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Purpose

This is a **research and design workspace** for building an ASR (Automatic Speech Recognition) scientific research automation Agent on top of the [OpenClaw](https://github.com/openclaw/openclaw) platform. It contains:

- `openclaw/` — OpenClaw open-source gateway (Node.js, read-only reference)
- `openclaw_researcher_agent_kb.md` — Authoritative implementation knowledge base (v3.0, source-verified + feasibility evaluation)
- `openclaw_researcher_framework_v4.html` — Framework design document (v3.0, Turn-Based orchestration)
- `doc/` — Archived earlier design document versions

## Key Architecture Reference

Always consult `openclaw_researcher_agent_kb.md` first. It supersedes the HTML design documents and has been verified against the actual OpenClaw source code. The **Appendix** section at the bottom lists all known discrepancies between the design docs and source behavior.

## OpenClaw Source Navigation

The `openclaw/` directory is the actual OpenClaw codebase. Key locations for understanding the Agent system:

- `openclaw/docs/concepts/session-tool.md` — `sessions_spawn` / `sessions_send` / `sessions_list` full spec
- `openclaw/docs/tools/subagents.md` — Sub-agent lifecycle, announce chain, nesting depth, tool policy
- `openclaw/docs/concepts/multi-agent.md` — Multi-agent routing, bindings, per-agent workspace/auth
- `openclaw/docs/concepts/agent-workspace.md` — Workspace file map (AGENTS.md, SOUL.md, TOOLS.md, skills/)
- `openclaw/docs/gateway/sandboxing.md` — Sandbox modes, scope, workspace access
- `openclaw/docs/gateway/configuration-reference.md` — Full `openclaw.json` config schema
- `openclaw/AGENTS.md` — Repository coding guidelines (for contributing to openclaw itself)

## Critical Behavioral Facts (verified from source)

These are easy to get wrong — the design HTML documents had errors on all of these:

1. **`sessions_spawn` is non-blocking** — returns `{status:"accepted", runId, childSessionKey}` immediately; completion is signaled via an **announce callback** message back to the requester channel
2. **Turn-Based orchestration** — each spawn must end the current turn; announce arrival triggers a new Orchestrator turn for the next phase. Cannot write a complete 8-step flow in one turn
3. **`ANNOUNCE_SKIP`** — sub-agent replies this to stay silent; it is NOT a completion signal itself
4. **Sub-agents cannot spawn** — default `maxSpawnDepth=1`; set `maxSpawnDepth: 2` to enable one level of nesting
5. **`runTimeoutSeconds` defaults to 0** (no timeout) — must be set explicitly in `agents.defaults.subagents.runTimeoutSeconds` or per `sessions_spawn` call
6. **Sub-agent context injection** — only `AGENTS.md` + `TOOLS.md` are injected; `SOUL.md`, `USER.md`, `IDENTITY.md` are NOT
7. **`sandbox` must be OFF** (`agents.defaults.sandbox.mode: "off"`) — default `workspaceAccess:"none"` creates an isolated sandbox workspace where sub-agents CANNOT read/write `state/` files
8. **`exec` timeout defaults to 1800s** (not 3600s) — must explicitly set `tools.exec.timeout: 3600` for ASR experiments
9. **`archiveAfterMinutes` default is 60**, not 180
10. **AGENTS.md is shared** across main + sub-agents — use role-conditional sections to separate Orchestrator workflow from sub-agent rules

## Planned Implementation Structure

When implementing the workspace files (to be placed at `~/.openclaw/workspace/`):

```
AGENTS.md          # Orchestrator workflow (8 phases, all spawn calls here)
TOOLS.md           # Tool usage conventions
skills/
  researcher-pipeline/SKILL.md
  experiment-runner/SKILL.md
  voyage-embed/SKILL.md
  critic-analyzer/SKILL.md
  state-manager/SKILL.md
  asr-domain/SKILL.md
scripts/
  fetch_papers.py       # arxiv + Haiku query gen + Sonnet extraction
  embed_papers.py       # voyage-3.5 + ChromaDB
  generate_survey.py    # RAG + Sonnet survey
  run_experiment.py     # venv + subprocess + MLflow + Haiku error summary
```

Agent model assignments: Opus 4.6 (main/planner/critic, thinking=high), Sonnet 4.6 (researcher/coder/reporter), Haiku 4.5 (in-script only for lightweight calls ~$0.001).

State is shared exclusively via `state/*.json/yaml/md` files — never through LLM context. `state/progress.json` tracks current PHASE for crash recovery.
