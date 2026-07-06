# Sisyphus Development Notes

## Architectural Principle

Sisyphus should be built as a minimal loop runtime.

The runtime owns the loop. Hosts own presentation. Tools own domain actions. Capabilities own side effects. Policies own permission decisions.

Keep these boundaries clear:

- `AgentRuntime` coordinates execution.
- `ModelProvider` talks to a model vendor.
- `Tool` describes and performs a model-callable action.
- `RuntimeContext` exposes controlled capabilities to tools.
- `PermissionPolicy` decides whether a capability may act.
- `RuntimeEvent` reports what happened.

## Proposed Package Shape

```text
sisyphus/
  core/
    runtime.py
    messages.py
    events.py
    results.py
    options.py
  models/
    base.py
  tools/
    base.py
    registry.py
    builtin/
      fs.py
      shell.py
  permissions/
    base.py
    workspace.py
  capabilities/
    fs.py
    shell.py
    network.py
    secrets.py
  hosts/
    cli.py
```

This structure is only a starting point. It should stay flexible while the first implementation discovers the right module boundaries.

## Core API Sketch

```python
class AgentRuntime:
    def __init__(
        self,
        model: ModelProvider,
        tools: list[Tool] | ToolRegistry | None = None,
        permissions: PermissionPolicy | None = None,
        system_prompt: str | None = None,
        config: RuntimeConfig | None = None,
    ) -> None:
        ...

    async def run(
        self,
        input: str | list[Message],
        *,
        context: RuntimeContext | None = None,
        options: RunOptions | None = None,
    ) -> RunResult:
        ...

    async def stream(
        self,
        input: str | list[Message],
        *,
        context: RuntimeContext | None = None,
        options: RunOptions | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        ...
```

`run()` should be implemented by consuming `stream()` and building a `RunResult`.

## Runtime Options

```python
@dataclass
class RunOptions:
    run_id: str | None = None
    max_iterations: int = 20
    timeout_seconds: float | None = None
    stream_tokens: bool = True
    metadata: dict = field(default_factory=dict)
```

`run_id` may be provided by a host application so external systems can correlate events.

## Messages and Content Blocks

The message model should be provider-neutral.

```python
@dataclass
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: list[ContentBlock]
```

Initial content blocks:

```python
@dataclass
class TextBlock:
    text: str

@dataclass
class ToolCallBlock:
    id: str
    name: str
    arguments: dict

@dataclass
class ToolResultBlock:
    tool_call_id: str
    content: str | dict | list
    is_error: bool = False
```

The runtime can add more block types later, but the first phase should keep the set small.

## Model Provider Development

The first provider implementation targets OpenAI-compatible chat completions APIs. It should support the official OpenAI endpoint by default, while still being easy to point at local gateways, mock servers, or self-hosted compatible services.

Direct construction should remain the primary configuration path:

```python
from sisyphus.models import OpenAIProvider

provider = OpenAIProvider(
    model="gpt-4.1",
    api_key="anything",
)
```

For OpenAI-compatible services that keep the standard path, override the base URL:

```python
provider = OpenAIProvider(
    model="my-model",
    api_key="anything",
    base_url="https://api.example.com/v1",
)
```

For services that expose chat completions at a different path, override `chat_completions_path`:

```python
provider = OpenAIProvider(
    model="my-model",
    api_key="anything",
    base_url="https://api.example.com",
    chat_completions_path="/openai/chat/completions",
)
```

For mock servers or gateways where the exact endpoint is already known, use `completions_url`:

```python
provider = OpenAIProvider(
    model="mock-model",
    api_key="anything",
    completions_url="https://dg3dl0.mockapi.dog/",
)
```

The provider also reads these environment variables when explicit constructor values are not supplied:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_CHAT_COMPLETIONS_PATH`
- `OPENAI_CHAT_COMPLETIONS_URL`

Use `OPENAI_CHAT_COMPLETIONS_URL` when a development server exposes one exact endpoint and should bypass `base_url + chat_completions_path` composition.

### Mock SSE Smoke Test

The development mock server used for the first provider pass can be called with:

```bash
curl -X POST "https://dg3dl0.mockapi.dog/" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream"
```

It returns OpenAI-style Server-Sent Events with `data:` lines, streamed `choices[0].delta.content` fragments, and a final `data: [DONE]` marker. A minimal Python smoke test against the same mock looks like this:

```python
import asyncio

from sisyphus.core.messages import Message, TextBlock
from sisyphus.models import OpenAIProvider


async def main() -> None:
    provider = OpenAIProvider(
        model="mock-model",
        api_key="anything",
        completions_url="https://dg3dl0.mockapi.dog/",
        timeout=15,
    )

    async for delta in provider.stream([Message.text("user", "hi")], []):
        for block in delta.content:
            if isinstance(block, TextBlock):
                print(block.text, end="", flush=True)


asyncio.run(main())
```

The mock is useful for checking SSE parsing and streaming behavior, but unit tests should continue to mock the HTTP boundary so the core test suite does not depend on network access.

## Tool Protocol

```python
class Tool(Protocol):
    name: str
    description: str
    input_schema: dict

    async def execute(self, ctx: RuntimeContext, **kwargs) -> ToolResult:
        ...
```

```python
@dataclass
class ToolResult:
    content: str | dict | list
    is_error: bool = False
    metadata: dict | None = None
```

Tool implementation rules:

- Tools should be async.
- Tools should use `RuntimeContext` for side effects.
- Tools should return structured results where useful.
- Tools should not directly bypass permissioned capabilities.
- Tool errors should be captured as tool results unless they indicate runtime failure.

## Capability Pattern

Capabilities are controlled interfaces to external effects.

Examples:

```python
content = await ctx.fs.read_text(path)
await ctx.fs.write_text(path, content)
result = await ctx.shell.run(command)
```

The capability should:

1. build a `PermissionRequest`
2. ask the `PermissionPolicy`
3. emit relevant events
4. perform the operation only if allowed
5. return a serializable result

This keeps tools simple and makes permissions consistent.

## Permission Model

```python
@dataclass
class PermissionRequest:
    kind: str
    action: str
    resource: str
    details: dict = field(default_factory=dict)

@dataclass
class PermissionDecision:
    allowed: bool
    reason: str | None = None
    require_approval: bool = False
```

The first policy can be a workspace policy:

```python
WorkspacePolicy(
    root=".",
    allow_read=True,
    allow_write=False,
    allow_shell=False,
)
```

Even if the first implementation focuses on files, the policy types should be generic enough for shell, network, browser, database, and host-specific capabilities.

## Event Stream

Events should be stable and serializable:

```python
@dataclass
class RuntimeEvent:
    type: str
    run_id: str
    sequence: int
    timestamp: datetime
    data: dict
```

Important constraints:

- Every event in a run has the same `run_id`.
- `sequence` increments monotonically within a run.
- `data` is JSON-serializable.
- Errors should be represented with serializable fields such as `message`, `code`, and `details`.
- Host adapters should not need access to internal runtime state to render progress.

## FastAPI Compatibility Without FastAPI Dependency

The core should not import FastAPI or define HTTP routes.

However, the core must be easy for a future FastAPI adapter to consume:

```python
async for event in runtime.stream(message):
    await websocket.send_json(event.to_dict())
```

The same stream should also support Server-Sent Events:

```python
async for event in runtime.stream(message):
    yield encode_sse(event)
```

This means the core event model must be ordered, incremental, and JSON-serializable from the beginning.

## CLI Host

The CLI should be a host adapter, not a separate runtime.

Expected commands:

```bash
sps --message "What is the weather today?"
sps --cwd ./project --message "Summarize this repository"
sps chat
```

The CLI should:

- load config
- construct `AgentRuntime`
- call `run()` or `stream()`
- render events
- exit with a useful status code

## Configuration Direction

A future config file may look like this:

```toml
[model]
provider = "openai"
model = "gpt-4.1"

[runtime]
max_iterations = 20

[workspace]
root = "."
read = true
write = false

[tools]
enabled = ["list_files", "read_file", "write_file", "shell"]

[tools.shell]
enabled = false
```

Config should remain optional. Direct Python construction should always be supported.

## Implementation Order

Recommended first implementation sequence:

1. Define message, content block, event, result, and option dataclasses.
2. Define `ModelProvider`, `Tool`, and `PermissionPolicy` protocols.
3. Implement `ToolRegistry`.
4. Implement `RuntimeContext` and workspace filesystem capability.
5. Implement `AgentRuntime.stream()`.
6. Implement `AgentRuntime.run()` as stream aggregation.
7. Add minimal built-in filesystem tools.
8. Add CLI wrapper.
9. Add tests for loop behavior, tool execution, permission denial, and event order.

## Design Guardrails

- Keep the core small.
- Prefer protocols and dataclasses over inheritance-heavy abstractions.
- Do not add orchestration concepts to the runtime.
- Do not make host framework assumptions in core.
- Do not let tools bypass capabilities for side effects.
- Treat event streaming as a foundational behavior, not an optional add-on.
- Add abstractions only when they protect the runtime boundary or remove real duplication.
