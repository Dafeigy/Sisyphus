# Sisyphus Next Step Plan

The next development pass should focus on making the minimal runtime kernel reliable before expanding tools or host adapters too far.

## Priority Order

1. Harden OpenAI-compatible streaming tool calls.
2. Add runtime boundary tests.
3. Normalize failed event payloads.
4. Improve CLI streaming output.
5. Expand filesystem tools conservatively.
6. Add a minimal optional configuration layer.

## Recommended Next Iteration

Suggested commit scope:

```text
feat: harden runtime tool loop and streaming tool calls
```

This iteration should make tool-calling behavior stable enough for later CLI, host adapter, and real tool work.

## Detailed Tasks

### 1. Aggregate Streaming Tool Call Fragments

Current provider streaming support handles simple text deltas well, but tool calls are simplified. Real OpenAI-compatible streaming APIs may split tool call fields across multiple deltas, especially `function.arguments`.

Implement support for:

- tool call `index`
- partial `id`
- partial `function.name`
- partial `function.arguments`
- final assembly into one complete `ToolCallBlock`
- multiple tool calls in the same assistant message

Add tests for:

- arguments streamed across several SSE events
- multiple streamed tool calls
- mixed text and tool call deltas if supported by provider behavior
- invalid JSON arguments falling back to `_raw`

### 2. Add Runtime Boundary Tests

Add focused tests for edge cases around the loop boundary:

- unknown tool call produces `tool.failed` and a tool result block with `is_error=True`
- tool exception produces `tool.failed` and continues through a tool result message where appropriate
- permission denied produces serializable failure details
- `max_iterations` produces `run.failed`
- provider failure produces `run.failed`
- `stream_tokens=False` suppresses `message.delta` events but still emits `message.completed`

These tests should lock down behavior before the runtime grows more capabilities.

### 3. Normalize Failure Event Data

Standardize `run.failed` and `tool.failed` payloads so host adapters can render them predictably.

Recommended fields:

- `message`
- `code`
- `details`
- `recoverable`

Avoid putting exception objects, SDK objects, file handles, paths as `Path` instances, or other non-serializable values into event data.

### 4. Improve CLI Streaming Output

Keep the CLI as a thin host over `AgentRuntime.stream()`, but make its output more useful:

- print text deltas as they arrive
- show concise tool start/completion messages
- render permission denials clearly
- return non-zero exit codes for failed runs
- keep `sps chat` simple and state-light

The CLI should not contain separate agent logic.

### 5. Expand Filesystem Tools Carefully

Keep the capability and permission boundary intact. Candidate additions:

- recursive `list_files`
- file metadata
- safe path validation details
- `search_files`
- later: patch/edit tools

Do not let tools perform direct filesystem side effects outside `RuntimeContext.fs`.

### 6. Add Minimal Optional Configuration

Add configuration only after the loop behavior is stable.

Start with a small TOML shape:

```toml
[model]
provider = "openai"
model = "gpt-4.1"
base_url = "https://api.openai.com/v1"

[runtime]
max_iterations = 20

[workspace]
root = "."
read = true
write = false

[tools]
enabled = ["list_files", "read_file", "mock_lookup"]
```

Configuration should remain optional. Direct Python construction must continue to be the primary API.

## Definition Of Done For The Next Pass

- OpenAI-compatible streaming tool call fragments are assembled correctly.
- Runtime boundary tests cover unknown tools, tool exceptions, permission denial, max iterations, provider failure, and `stream_tokens=False`.
- Failure event payloads are stable and JSON-serializable.
- `python -m unittest discover -s tests` passes.
- `python -m compileall sisyphus` passes.
- README or `PROGRESS.md` is updated if behavior or scope changes.
