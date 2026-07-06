import asyncio
import os

from sisyphus import AgentRuntime
from sisyphus.models import ModelConfig, OpenAIProvider
from sisyphus.permissions import WorkspacePolicy
from sisyphus.tools import builtin_tools


async def main() -> None:
    runtime = AgentRuntime(
        model=OpenAIProvider(
            model=os.getenv("OPENAI_MODEL", "sisyphus-mock-model"),
            api_key="anything",
            completions_url=os.getenv(
                "OPENAI_CHAT_COMPLETIONS_URL",
                "http://127.0.0.1:8881/v1/chat/completions",
            ),
        ),
        tools=builtin_tools(["list_files", "read_file", "mock_lookup", "echo"]),
        permissions=WorkspacePolicy(root=".", read=True, write=False),
        system_prompt="You are a concise repository assistant.",
        config=ModelConfig(metadata={"mock_scenario": os.getenv("SISYPHUS_MOCK_SCENARIO", "auto")}),
    )

    # result = await runtime.run("Read README.md and summarize this project in one paragraph.")
    # print(result.text)

    async for event in runtime.stream("List the files in this workspace and lookup mock project status."):
        print(event.to_dict())


asyncio.run(main())
