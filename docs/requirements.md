# Sisyphus Requirements

## Purpose

Sisyphus is a minimal, embeddable Python Agent Runtime.

Its job is to provide a controlled agent loop that can be embedded into command-line tools, desktop apps, web apps, backend services, automation scripts, and other Python workflows. The runtime should be small enough to understand, but extensible enough to support tools, permissions, event streaming, and multiple model providers.

## Product Positioning

Sisyphus is a runtime kernel, not a full agent product.

It should provide:

- a reusable agent loop
- a stable Python API
- a thin CLI
- model provider abstraction
- tool declaration and execution
- permission-aware capabilities
- real-time runtime events

It should not provide, in the first phase:

- multi-agent orchestration
- sub-agents
- team abstractions
- workflow graphs
- visual builders
- framework-specific server APIs
- persistent task management
- memory systems

## Naming Concept

Sisyphus refers to the figure who repeatedly lifts the stone and begins again.

For this project, the metaphor is the loop:

1. receive a message
2. ask the model what to do
3. execute a tool when requested
4. observe the result
5. continue the loop
6. stop when the model finishes or the runtime limit is reached

The runtime should make this loop explicit, inspectable, and controllable.

## Core Requirements

### Agent Runtime

The core package must expose an `AgentRuntime` object.

It should support:

- one-shot execution through `run()`
- event streaming through `stream()`
- model provider injection
- tool registry injection
- permission policy injection
- runtime options such as max iterations and timeout

The core runtime must not depend on FastAPI, WebSocket libraries, desktop UI frameworks, or specific host environments.

### Streaming First

`stream()` is a first-class API and should be treated as the source of truth.

`run()` should consume `stream()` internally and aggregate a final `RunResult`.

This ensures that REST, WebSocket, SSE, CLI, desktop UI, and logs all observe the same behavior.

### Runtime Events

The runtime must emit ordered, JSON-serializable events.

Minimum event shape:

```python
@dataclass
class RuntimeEvent:
    type: str
    run_id: str
    sequence: int
    timestamp: datetime
    data: dict
```

Initial event types:

- `run.started`
- `message.delta`
- `message.completed`
- `tool.started`
- `tool.delta`
- `tool.completed`
- `tool.failed`
- `permission.requested`
- `permission.resolved`
- `run.completed`
- `run.failed`

Events must not contain raw SDK objects, exception instances, open file handles, or non-serializable values.

### Tool System

Tools should be explicit execution units.

Minimum tool protocol:

```python
class Tool(Protocol):
    name: str
    description: str
    input_schema: dict

    async def execute(self, ctx: RuntimeContext, **kwargs) -> ToolResult:
        ...
```

Tools must declare:

- name
- description
- JSON-schema-compatible input schema
- async execution method

Tools should interact with the outside world through `RuntimeContext`, not through unrestricted direct calls.

### Runtime Context

`RuntimeContext` is the tool execution environment.

It should expose capability objects rather than raw global access:

```python
@dataclass
class RuntimeContext:
    cwd: Path
    fs: FileSystemCapability
    shell: ShellCapability
    network: NetworkCapability
    secrets: SecretStore
    events: EventSink
    metadata: dict
```

This allows different hosts to provide different environments:

- local filesystem for CLI
- virtual workspace for web apps
- restricted directories for desktop apps
- in-memory filesystem for tests
- database-backed documents for SaaS products

### Permissions

Permissions should be handled by a generic policy interface.

```python
class PermissionPolicy(Protocol):
    async def check(self, request: PermissionRequest) -> PermissionDecision:
        ...
```

Permission requests should represent side effects and sensitive access:

- filesystem read
- filesystem write
- shell execution
- network access
- secret access
- host-specific capabilities

Permission decisions should support:

- allow
- deny
- require approval
- reason message

The first implementation can focus on workspace file permissions, but the policy interface should not be filesystem-only.

### Model Providers

The runtime must not be tied to a single model vendor.

Minimum provider protocol:

```python
class ModelProvider(Protocol):
    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        system: str | None = None,
        config: ModelConfig | None = None,
    ) -> ModelResponse:
        ...
```

Providers should normalize vendor-specific responses into common runtime objects such as text blocks and tool call blocks.

### Host Embedding

Sisyphus should be easy to call from:

- Python code
- CLI
- web servers
- desktop apps
- scheduled jobs
- larger workflow systems

Host integrations should be thin wrappers around `run()` and `stream()`.

FastAPI integration is explicitly supported by the design, but should be implemented outside the first-phase core. A future adapter can convert runtime events to REST, Server-Sent Events, or WebSocket messages.

## First Phase Scope

The first phase should include:

- core runtime loop
- common message and content block types
- model provider protocol
- tool protocol and registry
- runtime context
- permission policy protocol
- workspace filesystem capability
- event stream
- `run()` aggregation
- minimal CLI
- basic documentation

The first phase should not include:

- FastAPI adapter
- persistent run store
- reconnectable streams
- browser automation
- MCP bridge
- memory
- sub-agents
- workflow graphs

