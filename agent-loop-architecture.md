# The Agent Loop

This is what Edwin's agent does on every turn. The green path works today. The red items are still missing — they unlock new capabilities and remove the rough edges.

```mermaid
flowchart TB
    User([👤 User])

    subgraph Loop["The agent loop"]
      direction TB

      A["1. User makes a request"]:::done
      LoadMem["2. Load relevant long-term memories<br/>(facts about the user, project history,<br/>past feedback that shaped how the AI behaves)"]:::missing
      Read["3. AI reads the conversation + decides next move"]:::done
      Stream["4. AI streams thinking, builds output, runs tools"]:::done

      Decide{"5. What can the AI do mid-turn?"}:::done

      Tool["Use a built-in tool<br/>(create / edit slide, search web,<br/>export deck)"]:::done
      Skill["Invoke a skill<br/>(brand recipe, deck outliner,<br/>packaged prompt)"]:::done
      ForkSkill["Run a skill in a forked sub-agent<br/>(isolated memory + tools + abort,<br/>so it can't disturb the parent)"]:::missing
      SubAgent["Dispatch a specialist sub-agent<br/>(scoped to a subtask with its own<br/>tool set and system prompt)"]:::missing
      Ask["Ask the user a question<br/>(approve plan, pick option)"]:::done
      Gate["Permission gate for risky steps<br/>(granular approval beyond plan-mode)"]:::missing

      Done["6. AI signals the request is done"]:::done
      ExtractMem["7. Extract notable facts to long-term memory<br/>(so future turns benefit from what we just learned)"]:::missing
    end

    User --> A --> LoadMem --> Read --> Stream --> Decide
    Decide --> Tool --> Stream
    Decide --> Skill --> Stream
    Decide --> ForkSkill --> Stream
    Decide --> SubAgent --> Stream
    Decide --> Ask --> Read
    Ask --> Gate
    Decide --> Done --> ExtractMem --> User

    subgraph Plumbing["Plumbing under the hood"]
      direction TB
      P1["One continuous turn loop on the frontend<br/>(shipped — agentLoop.js owns the whole turn through a single while loop;<br/>continuation POSTs happen inside the loop rather than via fresh user clicks)"]:::done
      P3["Race-free hand-off when the AI asks for input<br/>(shipped — interactive tool answers resolve a promise the loop is awaiting,<br/>so no two streams can ever overlap and clobber state)"]:::done
      P2["Frontend-only tools run in parallel mid-stream<br/>(deferred — Edwin has few FE-side tools today; coordinator pattern<br/>lands when subagent / forked-skill work needs it)"]:::missing
      P4["Progress saved live as the AI works<br/>(deferred — backend still drains the to_persist list after the SSE<br/>loop ends; FE-side per-message persistence not ported)"]:::missing
    end

    classDef done fill:#d4edda,stroke:#155724,color:#000
    classDef missing fill:#f8d7da,stroke:#721c24,color:#000,stroke-dasharray: 5 3
```

## Legend

- 🟢 **Green** — works in Edwin today.
- 🔴 **Red dashed** — still to come. Either a new capability the AI doesn't have yet (long-term memory, sub-agents, forked skills, granular permission gates) or a structural improvement that makes today's flow more robust.

## What each delta unlocks

| Missing piece | What it enables |
|---|---|
| **Long-term memory (load + extract)** | The AI carries useful context between conversations — user preferences, project specifics, past feedback — so it doesn't relearn the same things each session. |
| **Forked skills** | A skill can run in an isolated sandbox: its own memory, its own tool subset, its own abort signal. Useful for skills that change brand, language, or persona without polluting the parent conversation. |
| **Sub-agent dispatch** | The AI can hand off a subtask to a specialist mini-agent (with its own tools and prompt), get the result, and continue — instead of doing everything itself. |
| **Permission gates** | Granular "ask before this action" beyond the plan-mode coarse approval — so high-risk steps (overwrites, exports, deletions) can require explicit consent. |
| **Plumbing improvements** | Two of the four shipped on the `chat-loop-refactor` branch: the frontend now runs one continuous loop per turn, and user input is handed back to the loop race-free. This eliminates the class of bugs where state drifted on quick clicks or where the streaming UI didn't refresh after approval. The other two (parallel mid-stream tool dispatch + live per-message persistence) remain deferred — they only pay off once richer FE-side features land. |
