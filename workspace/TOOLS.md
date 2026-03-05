# Tool Usage Conventions

## bash (exec)

- All file paths use `~/.openclaw/workspace/` as the base directory.
- Expand `~` via `$HOME` when constructing paths in Python.
- Timeout: max 3600s for experiments, 120s for quick reads.
- Always check exit codes; non-zero means failure.

### Reading state files

```bash
cat ~/.openclaw/workspace/state/current_task.json
cat ~/.openclaw/workspace/state/iteration.json
```

### Writing state files

```bash
cat > ~/.openclaw/workspace/state/progress.json << 'EOF'
{"phase": 2, "status": "waiting_researcher"}
EOF
```

### Running Python scripts

```bash
cd ~/.openclaw/workspace && python scripts/fetch_papers.py \
  --task state/current_task.json \
  --output state/papers.json
```

## sessions_spawn

- Always set `runTimeoutSeconds` (default is 0 = no timeout).
- Keep `task` description short; pass data via state/ files.
- After calling sessions_spawn, end the current turn immediately.
- Sub-agent results arrive via announce callback in a new turn.

## Error Handling

- Capture stderr from bash commands.
- On script failure, write error details to `state/error.json`.
- Never silently swallow errors — fail fast.
