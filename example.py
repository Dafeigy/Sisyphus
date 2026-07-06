import asyncio

from sisyphus import AgentRuntime
from sisyphus.models import OpenAIProvider
from sisyphus.permissions import WorkspacePolicy
from sisyphus.tools import builtin_tools


async def main() -> None:
    runtime = AgentRuntime(
        model=OpenAIProvider(
            model="mock-model",
            api_key="anything",
            completions_url="https://dg3dl0.mockapi.dog/",
            # api_key defaults to OPENAI_API_KEY.
            # base_url can point to any OpenAI-compatible endpoint.
        ),
        tools=builtin_tools(["list_files", "read_file", "mock_lookup"]),
        permissions=WorkspacePolicy(root=".", read=True, write=False),
        system_prompt="You are a concise repository assistant.",
    )

    # result = await runtime.run("Read README.md and summarize this project in one paragraph.")
    # print(result.text)

    async for event in runtime.stream("List the files in this workspace."):
        print(event.to_dict())


asyncio.run(main())