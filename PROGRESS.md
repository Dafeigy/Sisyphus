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
- Assembles OpenAI-compatible streaming tool call fragments by `index`, including partial ids, names, and arguments.
- Supports multiple tool calls in one streamed assistant message.
- Falls back to `_raw` for invalid streamed tool arguments that cannot be parsed as JSON.
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
- Normalizes `run.failed` payloads with `message`, `code`, `details`, and `recoverable`.
- Normalizes `tool.failed` payloads with `message`, `code`, `details`, and `recoverable`.
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
- Added framework-free SSE helpers for host adapters:
  - `encode_sse`
  - `encode_sse_comment`
  - `iter_sse`
- SSE helpers encode runtime event type, sequence id, and JSON payload without adding a web-framework dependency to core.

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
- Renders streamed text deltas and concise tool status messages.
- Returns a non-zero exit code when the run emits `run.failed`.

### Development Mock LLM Host

- Added an optional FastAPI-based OpenAI-compatible mock LLM server outside the core runtime.
- Supports no-install startup with `python -m sisyphus.hosts.mock_llm`.
- Added optional `sps-mock-llm` entry point for installed environments.
- Supports `/`, `/chat/completions`, and `/v1/chat/completions`.
- Supports non-streaming and SSE streaming chat completions.
- Streams text deltas, fragmented tool-call arguments, and multiple tool calls in one assistant message.
- Supports explicit `mock_scenario` values for message-only, tool-call-only, text-plus-tool-call, and multiple-tool-call responses.
- Returns final text after the runtime sends tool result messages back to the mock server.
- Updated `example.py` to target the local mock endpoint by default while still allowing `OPENAI_CHAT_COMPLETIONS_URL` override.

### Documentation

- Updated README with a minimal embedding example.
- Added local mock LLM smoke-test instructions to README and development notes.
- Added current status summary to README.
- Added this detailed progress tracker.

### Tests

- Added provider tests for:
  - OpenAI-compatible payload construction.
  - endpoint URL configuration.
  - environment variable configuration.
  - tool call parsing.
  - SSE text delta parsing.
  - streamed tool-call argument assembly.
  - multiple streamed tool calls.
  - mixed text and tool-call streaming deltas.
  - invalid streamed tool-call JSON fallback.
- Added runtime tests for:
  - streamed text aggregation.
  - tool call execution and loop continuation.
  - filesystem capability permission events.
  - built-in file tool capability usage.
  - unknown tool failure boundaries.
  - tool exceptions.
  - permission denied tool failures.
  - max iteration failures.
  - provider failures.
  - `stream_tokens=False` behavior.
- Added mock LLM helper tests for:
  - multiple tool-call selection.
  - message-only, tool-call-only, and multiple-tool-call scenarios.
  - SSE tool-call argument fragmentation.
  - non-streaming OpenAI-compatible response shape.
- Added host SSE helper tests for:
  - runtime event SSE encoding.
  - event id and event type fields.
  - multiline JSON data handling.
  - heartbeat/comment encoding.
- Current standard-library test command:

```bash
python -m unittest discover -s tests
```

- Current result: 32 tests passing.

## Mock Or Incomplete Areas

- Tool content is still intentionally lightweight for development.
- `mock_lookup` and `echo` are development tools, not production domain tools.
- Filesystem tools are minimal and do not yet handle richer file metadata, recursive listing, binary content, or patch-style edits.
- Shell, network, secret store, and browser capabilities are not implemented yet.
- Permission approval workflows are not implemented yet; policy decisions are immediate allow or deny.
- CLI rendering is still intentionally minimal, but now consumes the runtime event stream directly.
- `AgentRuntime` does not yet expose a resumable run store or persistent history.
- Production FastAPI and WebSocket adapters are intentionally out of core scope and not implemented.
- RuntimeEvent-to-SSE text encoding is available, but complete HTTP route adapters remain host-specific.
- The FastAPI mock LLM server is a development/test host, not a runtime adapter.
- Multi-agent orchestration, sub-agents, workflow graphs, memory, and persistent task management remain non-goals for the first phase.

## Recommended Next Steps

1. Expand built-in filesystem tools only where they preserve the capability and permission boundaries.
2. Add minimal optional TOML configuration while keeping direct Python construction primary.
3. Add packaging metadata for dependencies and optional development extras.
4. Consider a tiny host example that wires `encode_sse(event)` into a framework-specific `text/event-stream` response without moving that dependency into core.

## Verification Notes

The current implementation was verified with:

```bash
python -m unittest discover -s tests
python -m compileall sisyphus
```

`pytest` may fail to start in the current local environment if optional test-runner dependencies such as `pygments` are missing. The standard-library `unittest` suite currently passes.
