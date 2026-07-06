# Sisyphus Implementation Progress

This file tracks the current implementation state against the first-phase runtime described in `docs/requirements.md` and `docs/development.md`.

## Completed

### Model Provider

- Added an OpenAI-compatible chat completions provider.
- Supports default OpenAI-style `/chat/completions` endpoint composition.
- Supports custom `base_url`, `chat_completions_path`, and exact `completions_url`.
- Reads endpoint configuration from environment variables:
  - `OPENAI_API_KEY`
  - `OPENAI_BASE_URL`
  - `OPENAI_CHAT_COMPLETIONS_PATH`
  - `OPENAI_CHAT_COMPLETIONS_URL`
- Supports non-streaming completion requests.
- Supports SSE streaming responses with OpenAI-style `data:` lines and `[DONE]`.
- Serializes provider-neutral messages and tool specs into OpenAI-compatible payloads.
- Parses text responses and tool calls into provider-neutral content blocks.

### Core Runtime Types

- Added provider-neutral message and content block types:
  - `Message`
  - `TextBlock`
  - `ToolCallBlock`
  - `ToolResultBlock`
- Added model provider contracts:
  - `ModelProvider`
  - `ToolSpec`
  - `ModelConfig`
  - `ModelResponse`
  - `ModelStreamDelta`
- Added runtime support types:
  - `RuntimeEvent`
  - `RunOptions`
  - `RunResult`
  - `RuntimeContext`

### Runtime Loop

- Added `AgentRuntime`.
- Implemented `AgentRuntime.stream()` as the source-of-truth execution path.
- Implemented `AgentRuntime.run()` by consuming `stream()` and aggregating a `RunResult`.
- Emits ordered runtime events with stable `run_id` and monotonic sequence numbers.
- Supports string input and explicit `list[Message]` input.
- Sends tool specs to the model provider.
- Executes requested tool calls and appends tool result messages back into the loop.
- Stops when the assistant returns no tool calls.
- Fails with a `run.failed` event when `max_iterations` is reached.
- Supports optional timeout through `RunOptions.timeout_seconds`.

### Events

- Added JSON-serializable runtime events.
- Implemented initial event coverage:
  - `run.started`
  - `message.delta`
  - `message.completed`
  - `tool.started`
  - `tool.completed`
  - `tool.failed`
  - `permission.requested`
  - `permission.resolved`
  - `run.completed`
  - `run.failed`
- Added `RuntimeEvent.to_dict()` for host adapters.

### Tools

- Added `Tool` protocol.
- Added `ToolResult`.
- Added `ToolRegistry`.
- Added development mock tools:
  - `mock_lookup`
  - `echo`
- Added basic filesystem tools:
  - `list_files`
  - `read_file`
  - `write_file`
- Filesystem tools use `RuntimeContext.fs` instead of bypassing runtime capabilities.

### Permissions And Capabilities

- Added generic permission contracts:
  - `PermissionRequest`
  - `PermissionDecision`
  - `PermissionPolicy`
- Added `AllowAllPolicy`.
- Added `WorkspacePolicy` with workspace-root checks.
- Added `FileSystemCapability`.
- Filesystem capability emits permission request and resolution events.
- Filesystem reads and writes are routed through the permission policy.

### CLI Host

- Added a thin CLI host module.
- Added `sps` entry point in `pyproject.toml`.
- Supports one-shot messages.
- Supports simple interactive chat mode.
- Uses the same `AgentRuntime` path as embedded callers.
- Configures OpenAI-compatible provider, built-in tools, and workspace permissions.

### Documentation

- Updated README with a minimal embedding example.
- Added current status summary to README.
- Added this detailed progress tracker.

### Tests

- Added provider tests for:
  - OpenAI-compatible payload construction.
  - endpoint URL configuration.
  - environment variable configuration.
  - tool call parsing.
  - SSE text delta parsing.
- Added runtime tests for:
  - streamed text aggregation.
  - tool call execution and loop continuation.
  - filesystem capability permission events.
  - built-in file tool capability usage.
- Current standard-library test command:

```bash
python -m unittest discover -s tests
```

- Current result: 10 tests passing.

## Mock Or Incomplete Areas

- Tool content is still intentionally lightweight for development.
- `mock_lookup` and `echo` are development tools, not production domain tools.
- Filesystem tools are minimal and do not yet handle richer file metadata, recursive listing, binary content, or patch-style edits.
- Shell, network, secret store, and browser capabilities are not implemented yet.
- Permission approval workflows are not implemented yet; policy decisions are immediate allow or deny.
- CLI rendering is minimal and currently prints final text or raw streamed event dictionaries.
- `AgentRuntime` does not yet expose a resumable run store or persistent history.
- FastAPI, WebSocket, and SSE adapters are intentionally out of core scope and not implemented.
- Multi-agent orchestration, sub-agents, workflow graphs, memory, and persistent task management remain non-goals for the first phase.

## Recommended Next Steps

1. Tighten runtime error behavior so model/provider failures always produce useful serializable `run.failed` details.
2. Improve streaming tool-call assembly for providers that emit tool call arguments across multiple deltas.
3. Add tests for permission denial and unknown tool calls.
4. Add a small SSE encoder helper outside the core runtime, or document how hosts should encode `RuntimeEvent.to_dict()`.
5. Expand built-in filesystem tools only where they preserve the capability and permission boundaries.
6. Improve CLI event rendering while keeping the CLI as a thin host.
7. Add packaging metadata for dependencies and optional development extras.

## Verification Notes

The current implementation was verified with:

```bash
python -m unittest discover -s tests
python -m compileall sisyphus
```

`pytest` may fail to start in the current local environment if optional test-runner dependencies such as `pygments` are missing. The standard-library `unittest` suite currently passes.
