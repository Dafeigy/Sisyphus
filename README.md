# Sisyphus

Sisyphus is a minimal Python Agent Runtime.

The name comes from Sisyphus, who keeps lifting the stone and beginning again. In this project, that image becomes a runtime idea: an agent is a controlled loop. It observes, reasons, acts through tools, receives results, and continues until the task is done or the runtime stops it.

Sisyphus is not designed to be a multi-agent platform, team system, or workflow graph engine. It is meant to be a small embeddable kernel that can be called from a CLI, desktop app, web app, backend service, scheduled job, or any Python workflow.

## Design Goals

- Keep the agent loop small, explicit, and easy to embed.
- Expose both one-shot execution and real-time event streaming.
- Make tools declarative, discoverable, permission-aware, and auditable.
- Route filesystem, shell, network, and other side effects through runtime capabilities.
- Keep framework integrations such as FastAPI outside the core package.
- Prefer simple host adapters over large orchestration abstractions.

## Non-Goals

Sisyphus intentionally avoids these concepts in the core runtime:

- multi-agent systems
- sub-agents
- teams
- workflow graphs
- complex planning engines
- product-specific UI assumptions

These can be built around Sisyphus if a host application needs them, but they should not shape the core.

## Core Idea

```text
Message in
  -> AgentRuntime
  -> ModelProvider
  -> ToolCall
  -> Tool.execute(ctx)
  -> PermissionPolicy
  -> RuntimeEvent stream
Message out
```

The runtime should expose two primary APIs:

```python
result = await runtime.run("Summarize this project")
```

```python
async for event in runtime.stream("Summarize this project"):
    handle(event)
```

`run()` is the convenient API. `stream()` is the foundational API. CLI output, REST responses, WebSocket updates, Server-Sent Events, desktop timelines, and logs should all be able to consume the same runtime event stream.

## Minimal Embedding Example

```python
from sisyphus import AgentRuntime
from sisyphus.models import OpenAIProvider
from sisyphus.permissions import WorkspacePolicy
from sisyphus.tools import builtin_tools

runtime = AgentRuntime(
    model=OpenAIProvider(model="gpt-4.1"),
    tools=builtin_tools(["list_files", "read_file"]),
    permissions=WorkspacePolicy(root=".", read=True, write=False),
)

result = await runtime.run("Summarize the README")
print(result.text)
```

## CLI Direction

The CLI should be a thin host over the same runtime:

```bash
sps --message "What is the weather today?"
sps --cwd ./my-project --message "Summarize this repository"
sps chat
```

The CLI should not contain special agent logic. It should configure a runtime, call `run()` or `stream()`, and render events.

## Documentation

- [Requirements](docs/requirements.md)
- [Development Notes](docs/development.md)

