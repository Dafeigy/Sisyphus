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
import asyncio

from sisyphus import AgentRuntime
from sisyphus.models import OpenAIProvider
from sisyphus.permissions import WorkspacePolicy
from sisyphus.tools import builtin_tools


async def main() -> None:
    runtime = AgentRuntime(
        model=OpenAIProvider(
            model="gpt-4.1",
            # api_key defaults to OPENAI_API_KEY.
            # base_url can point to any OpenAI-compatible endpoint.
        ),
        tools=builtin_tools(["list_files", "read_file", "mock_lookup"]),
        permissions=WorkspacePolicy(root=".", read=True, write=False),
        system_prompt="You are a concise repository assistant.",
    )

    result = await runtime.run("Read README.md and summarize this project in one paragraph.")
    print(result.text)

    async for event in runtime.stream("List the files in this workspace."):
        print(event.to_dict())


asyncio.run(main())
```

`run()` is the convenient API. `stream()` exposes the same loop as ordered,
JSON-serializable events for CLIs, logs, Server-Sent Events, WebSockets, or
desktop timelines.

## Host Event Streaming

Runtime events are transport-neutral. Host applications can send the same
event stream over WebSockets as JSON, or over Server-Sent Events with the small
SSE encoder:

```python
from sisyphus.hosts import encode_sse


async def sse_response(runtime, message):
    async for event in runtime.stream(message):
        yield encode_sse(event)
```

For WebSocket hosts, send the same runtime event dictionary through the
framework's JSON helper:

```python
async for event in runtime.stream(message):
    await websocket.send_json(event.to_dict())
```

The core runtime does not import web frameworks or define HTTP routes.

## Optional TOML Config

Hosts can still construct everything directly in Python, but the CLI can also
load a small TOML config:

```toml
[model]
provider = "openai"
model = "sisyphus-mock-model"
completions_url = "http://127.0.0.1:8881/v1/chat/completions"
mock_scenario = "auto"

[runtime]
max_iterations = 20
stream_tokens = true

[workspace]
root = "."
read = true
write = false

[tools]
enabled = ["list_files", "read_file", "mock_lookup", "echo"]
```

Use it with the CLI:

```bash
python -m sisyphus.hosts.cli --config sisyphus.toml --message "List files"
```

Command-line values such as `--model`, `--cwd`, `--base-url`,
`--completions-url`, and `--max-iterations` override the config file.
When `--config` is omitted, the CLI looks for `sisyphus.toml` and then
`.sisyphus.toml` in the current directory.

Validate config and CLI setup without running a model request:

```bash
python -m sisyphus.hosts.cli --config sisyphus.toml --check
```

Config validation checks supported providers, enabled built-in tools, runtime
limits, TOML shape, and workspace root setup.

Workspace file permissions can be configured as booleans or explicit modes:

```toml
[workspace]
read = "ask"
write = "ask"
```

The built-in CLI can validate this config, but interactive approval is provided
by host applications through the permission policy API.

## File Tools And Approval

Built-in filesystem tools stay behind `RuntimeContext.fs`, so reads and writes
always pass through the configured permission policy. `read_file` supports an
optional `max_chars` limit, and `write_file` supports overwrite or append:

```python
tools=builtin_tools(["read_file", "write_file"])
```

Host applications can require approval dynamically:

```python
from sisyphus.permissions import ApprovalDecision, ApprovalPermissionPolicy, WorkspacePolicy


def approve(request, decision):
    if request.action == "read":
        return ApprovalDecision(True, "Allow this read once.")
    return ApprovalDecision(True, "Allow future writes to this file.", remember=True)


permissions = ApprovalPermissionPolicy(
    WorkspacePolicy(root=".", read="ask", write="ask"),
    approve,
)
```

Returning `remember=True` automatically allows future requests for the same
kind, action, and resource. Permission requests include tool-call details when
the runtime is executing a tool.

## Development Setup

Install optional development dependencies when you want pytest, linting, type
checking, and build tooling:

```bash
pip install -e ".[dev]"
```

Useful local verification commands:

```bash
python -m unittest discover -s tests
python -m compileall sisyphus
```

## Current Status

Sisyphus currently has a first-pass runtime kernel in place:

- OpenAI-compatible chat completions provider with normal and SSE streaming paths.
- Provider-neutral messages, text blocks, tool call blocks, and tool result blocks.
- `AgentRuntime.stream()` as the source-of-truth loop and `AgentRuntime.run()` as aggregation.
- Ordered, JSON-serializable runtime events.
- Tool protocol, registry, mock tools, and basic workspace filesystem tools.
- Workspace permission policy and permission-aware filesystem capability.
- Dynamic file permission approval for one-off or remembered decisions.
- Thin CLI host through the `sps` command.
- Framework-free SSE encoding helpers for exposing runtime events from host adapters.
- Optional TOML config loading for CLI/runtime host setup.
- Config validation, default config discovery, and CLI `--check`.
- Optional `dev` dependency extra for local development tools.
- Optional FastAPI mock LLM host for local OpenAI-compatible streaming and tool-call smoke tests.
- Unit coverage for provider payloads, streaming parsing, runtime loop behavior, tool execution, and filesystem capability events.

Detailed implementation progress is tracked in [PROGRESS.md](PROGRESS.md).

## Local Mock LLM

For local runtime testing without depending on a remote mock endpoint, start the
OpenAI-compatible FastAPI service from the repository root:

```bash
python -m sisyphus.hosts.mock_llm
```

If `fastapi` or `uvicorn` is missing, install only the server runtime
dependencies. This does not install the project and does not require
`hatchling`:

```bash
pip install fastapi "uvicorn[standard]"
```

Then run the example or CLI in another terminal:

```bash
python example.py
python -m sisyphus.hosts.cli --completions-url http://127.0.0.1:8881/v1/chat/completions --model sisyphus-mock-model --message "List files and lookup mock project status"
```

If the project has been installed, the equivalent console scripts are
`sps-mock-llm` and `sps`.

The mock service streams OpenAI-style `data:` events, emits fragmented tool-call arguments, supports multiple tool calls in one assistant message, and returns a final text response after the runtime sends tool results back.

The mock response shape can be selected with `mock_scenario` in the request
payload. `example.py` reads this from `SISYPHUS_MOCK_SCENARIO`:

```bash
SISYPHUS_MOCK_SCENARIO=message python example.py
SISYPHUS_MOCK_SCENARIO=tool_call python example.py
SISYPHUS_MOCK_SCENARIO=text_and_tool_call python example.py
SISYPHUS_MOCK_SCENARIO=multiple_tool_calls python example.py
```

In PowerShell:

```powershell
$env:SISYPHUS_MOCK_SCENARIO = "tool_call"
python example.py
```

Supported scenarios are `auto`, `message`, `tool_call`, `text_and_tool_call`,
and `multiple_tool_calls`.

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
