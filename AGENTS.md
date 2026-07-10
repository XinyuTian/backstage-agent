# Agent Instructions

## Project Purpose

This repository is a local-first Python agent for Backstage casting workflows. It scans recent Backstage notification emails, extracts projects and roles, screens them against an actor profile with cheap deterministic checks plus LLM calls, records decisions in SQLite, and drafts or blocks application attempts conservatively. The daily workflow is intended to run once per day and notify the user on macOS when finished.

## Required Startup Workflow

Before beginning a future task, normally follow this order:

1. Read `AGENTS.md`.
2. Read `PROJECT_STATE.md`.
3. Read the most recent relevant entries in `CHANGELOG.md`.
4. Read `ARCHITECTURE.md` only when architectural context is needed.
5. Identify the specific modules related to the task.
6. Read only the relevant source files and tests.
7. Do not scan the entire repository unless the task genuinely requires it.

These documentation files are summaries for orientation. The source code and tests remain the final source of truth. When documentation conflicts with implementation, trust the implementation and correct the documentation as part of the task.

## Context-Efficient Reading Rules

- Do not automatically read every source file.
- Prefer targeted searches with `rg` over broad repository scans.
- Start from relevant entry points, interfaces, tests, and module documentation.
- Read a specific function, class, module, or directory before expanding the search.
- Avoid reopening files whose relevant content is already available in the current context.
- Do not read generated files, dependency directories, build output, caches, logs, local browser profiles, SQLite backups, or large data files unless required.
- Use the existing repository structure to locate relevant code. For example, CLI behavior starts in `src/backstage_agent/cli.py`, orchestration in `src/backstage_agent/agent.py`, persistence in `src/backstage_agent/storage.py`, and dashboard behavior in `src/backstage_agent/ui.py`.
- Use `docs/module-guide.md` for a quick module map before opening source files.
- When changing parser or screener behavior, inspect the matching test file first so the current edge cases stay visible.

## Code Change Rules

- Make the smallest change that correctly solves the task.
- Avoid unrelated refactoring.
- Preserve the existing architecture and coding style unless there is a clear reason to change them.
- Search for existing utilities and patterns before introducing new abstractions.
- Do not duplicate existing parser, identifier, storage, or LLM-provider logic.
- Do not silently change unrelated behavior, especially daily scan defaults, dry-run safety, or dashboard status semantics.
- Keep screening status separate from application outcomes. An application blocker should not turn an approved screening result into a rejected or generic "Needs Check" screening result.
- Add or update tests when behavior changes.
- Run the most relevant tests after making a change, usually a targeted `python3 -m pytest ...` invocation. Run the full suite when the change crosses module boundaries.
- Clearly report tests that were not run or could not be run.

## Documentation Maintenance Rules

- Update `PROJECT_STATE.md` when current functionality, priorities, blockers, known issues, or implementation status changes.
- Add a concise `CHANGELOG.md` entry when user-visible behavior, important internal behavior, interfaces, configuration, automation, storage schema, or architecture changes.
- Update `ARCHITECTURE.md` only when module boundaries, system flow, storage, integrations, or architectural decisions change.
- Update `README.md` when installation, setup, configuration, daily operation, or command usage changes.
- Update files inside `docs/` when documented module behavior changes.
- Trivial formatting changes, comments, or minor refactoring do not necessarily require a changelog entry.

## Completion Checklist

- Relevant code inspected.
- Minimal implementation completed.
- Relevant tests run.
- Documentation updated where necessary.
- Known limitations reported.
- No unrelated files modified.

## Communication Rules

Final task summaries should include:

- what changed
- why it changed
- which files were changed
- what tests were run
- any remaining limitations, risks, or follow-up work

Keep summaries concrete and repository-specific. Mention when live external actions, browser-backed Backstage access, or notification delivery were not verified.
