---
title: "Codebase Inspection — Inspect codebases w/ pygount: LOC, languages, ratios"
sidebar_label: "Codebase Inspection"
description: "Inspect codebases w/ pygount: LOC, languages, ratios"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Codebase Inspection

Inspect codebases w/ pygount: LOC, languages, ratios.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/software-development/codebase-inspection` |
| Version | `1.0.0` |
| Author | Hermes Agent |
| License | MIT |
| Platforms | linux, macos, windows, freebsd |
| Tags | `LOC`, `Code Analysis`, `pygount`, `Codebase`, `Metrics`, `Repository` |
| Related skills | [`github`](/docs/user-guide/skills/bundled/software-development/software-development-github) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Hermes loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Codebase Inspection with pygount

Analyze repositories for lines of code, language breakdown, file counts, and code-vs-comment ratios using `pygount`.

## When to Use

- User asks for LOC (lines of code) count
- User wants a language breakdown of a repo
- User asks about codebase size or composition
- User wants code-vs-comment ratios
- General "how big is this repo" questions

## Prerequisites

Use `terminal` with a user-owned developer environment, not system pip or
the shared Hermes venv. Resolve the active profile before provisioning.
On FreeBSD, verify a native Python path first (for example
`/usr/local/bin/python3.12`); with install approval:

```bash
PROFILE_HOME="${HERMES_HOME:-$HOME/.hermes}"
uv venv --python /usr/local/bin/python3.12 "$PROFILE_HOME/tool-envs/developer"
DEVELOPER_PY="$PROFILE_HOME/tool-envs/developer/bin/python"
```

Reuse that environment if it already exists. On Linux/macOS choose the
verified interpreter on that host; Windows venvs use `Scripts/python.exe`.
Use `write_file` to create a task-local `developer.in` containing `pygount`
(and `debugpy` only if needed), resolve and review a native hash-locked set,
then install explicitly into the environment:

```bash
uv pip compile --python "$DEVELOPER_PY" --generate-hashes developer.in -o developer.lock
uv pip install --python "$DEVELOPER_PY" --require-hashes -r developer.lock
uv pip check --python "$DEVELOPER_PY"
PYGOUNT="$PROFILE_HOME/tool-envs/developer/bin/pygount"
"$PYGOUNT" --help
```

Use the selected absolute `PYGOUNT` path for every command below (Windows:
the venv's `Scripts/pygount.exe`). Re-establish these task-local variables
in each new terminal process; no global PATH changes or cross-process venv
activation assumptions. Never bypass externally managed Python protections
with `--break-system-packages`.

## 1. Basic Summary (Most Common)

Get a full language breakdown with file counts, code lines, and comment lines:

```bash
cd /path/to/repo
"$PYGOUNT" --format=summary \
  --folders-to-skip=".git,node_modules,venv,.venv,__pycache__,.cache,dist,build,.next,.tox,.eggs,*.egg-info" \
  .
```

**IMPORTANT:** Always use `--folders-to-skip` to exclude dependency/build directories, otherwise pygount will crawl them and take a very long time or hang.

## 2. Common Folder Exclusions

Adjust based on the project type:

```bash
# Python projects
--folders-to-skip=".git,venv,.venv,__pycache__,.cache,dist,build,.tox,.eggs,.mypy_cache"

# JavaScript/TypeScript projects
--folders-to-skip=".git,node_modules,dist,build,.next,.cache,.turbo,coverage"

# General catch-all
--folders-to-skip=".git,node_modules,venv,.venv,__pycache__,.cache,dist,build,.next,.tox,vendor,third_party"
```

## 3. Filter by Specific Language

```bash
# Only count Python files
"$PYGOUNT" --suffix=py --format=summary --folders-to-skip=".git,venv,.venv,__pycache__" .

# Only count Python and YAML
"$PYGOUNT" --suffix=py,yaml,yml --format=summary --folders-to-skip=".git,venv,.venv,__pycache__" .
```

## 4. Detailed File-by-File Output

```bash
# Default format shows per-file breakdown
"$PYGOUNT" --folders-to-skip=".git,node_modules,venv" .

# Sort by code lines (pipe through sort)
"$PYGOUNT" --folders-to-skip=".git,node_modules,venv" . | sort -t$'\t' -k1 -nr | head -20
```

## 5. Output Formats

```bash
# Summary table (default recommendation)
"$PYGOUNT" --format=summary --folders-to-skip=".git,node_modules,venv,.venv" .

# JSON output for programmatic use
"$PYGOUNT" --format=json --folders-to-skip=".git,node_modules,venv,.venv" .

# Pipe-friendly: Language, file count, code, docs, empty, string
"$PYGOUNT" --format=summary --folders-to-skip=".git,node_modules,venv,.venv" .
```

## 6. Interpreting Results

The summary table columns:
- **Language** — detected programming language
- **Files** — number of files of that language
- **Code** — lines of actual code (executable/declarative)
- **Comment** — lines that are comments or documentation
- **%** — percentage of total

Special pseudo-languages:
- `__empty__` — empty files
- `__binary__` — binary files (images, compiled, etc.)
- `__generated__` — auto-generated files (detected heuristically)
- `__duplicate__` — files with identical content
- `__unknown__` — unrecognized file types

## Pitfalls

1. **Always exclude .git, node_modules, venv** — without `--folders-to-skip`, pygount will crawl everything and may take minutes or hang on large dependency trees.
2. **Markdown shows 0 code lines** — pygount classifies all Markdown content as comments, not code. This is expected behavior.
3. **JSON files show low code counts** — pygount may count JSON lines conservatively. For accurate JSON line counts, use `wc -l` directly.
4. **Large monorepos** — for very large repos, consider using `--suffix` to target specific languages rather than scanning everything.
