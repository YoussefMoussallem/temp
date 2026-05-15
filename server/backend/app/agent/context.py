"""
Context assembly — backend half.

Port of src/context.ts. Source has TWO concerns mixed:
  - File reading (git status, CLAUDE.md from disk) — DESKTOP per Q5
  - Prompt assembly (combine into system prompt) — BACKEND (this file)

This module is the BACKEND half: receives parsed context data from the
desktop in the /turn payload, assembles the system prompt the LLM sees.
The DESKTOP half (running git, reading CLAUDE.md) lives in
desktop/BimCode/Agent/context.cs (lands in Phase 1.6).

DEFERRED:
  - Memoization with cache invalidation → Phase 3
  - System prompt injection (cache breaking, ant-only) → Phase 3
  - Memory file injection from `services/extractMemories/` → Phase 5
  - Bare mode handling → Phase 5
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SystemContext:
    """
    System-level context shipped from desktop in /turn request.

    Mirrors the data assembled by src/context.ts:getSystemContext, but the
    file-reading happens on desktop and the result is sent here.
    """

    git_status: str | None = None
    branch: str | None = None
    main_branch: str | None = None
    user_name: str | None = None
    recent_commits: str | None = None
    # Cache-breaker injection (ant-only feature in source). Phase 3.
    cache_breaker: str | None = None


@dataclass
class UserContext:
    """
    User-level context: CLAUDE.md + current date.

    Mirrors src/context.ts:getUserContext, but the CLAUDE.md reading
    happens on desktop and the rendered text is sent here.
    """

    claude_md: str | None = None
    current_date: str | None = None


def assemble_system_prompt(
    base_system_prompt: str,
    system_context: SystemContext | None = None,
    user_context: UserContext | None = None,
) -> str:
    """
    Assemble the final system prompt sent to the LLM.

    Combines:
      - The agent's base system prompt (instructions, persona)
      - SystemContext (git status from desktop)
      - UserContext (CLAUDE.md from desktop, current date)

    v1 keeps the layout simple — single concatenation with section headers.
    Source's getSystemContext / getUserContext output a Record<string, string>
    that gets joined later; same effect.
    """
    parts: list[str] = [base_system_prompt]

    if system_context:
        if system_context.git_status:
            git_section = ["\n# Git Status", system_context.git_status]
            if system_context.branch:
                git_section.append(f"Current branch: {system_context.branch}")
            if system_context.main_branch:
                git_section.append(
                    f"Main branch (you will usually use this for PRs): {system_context.main_branch}"
                )
            if system_context.user_name:
                git_section.append(f"Git user: {system_context.user_name}")
            if system_context.recent_commits:
                git_section.append(f"Recent commits:\n{system_context.recent_commits}")
            parts.append("\n".join(git_section))

        if system_context.cache_breaker:
            parts.append(f"\n[CACHE_BREAKER: {system_context.cache_breaker}]")

    if user_context:
        if user_context.current_date:
            parts.append("\n" + user_context.current_date)
        if user_context.claude_md:
            parts.append("\n# Project Instructions (CLAUDE.md)\n" + user_context.claude_md)

    return "\n".join(parts)
