import asyncio
import os
import argparse
import research_engine.retrievers as retrievers

async def mock_search(query: str, max_results: int):
    print("MOCK SEARCH HIT FOR:", query)
    return [{"title": "Mock Title", "url": "https://example.com", "snippet": "Paris is the capital of France and its largest city."}]

# Mock the retriever chain to bypass network
retrievers._CHAIN = (("mock", mock_search),)

from research_engine.cli import _drive

async def main():
    os.environ["CUSTOM_BASE_URL"] = "http://localhost:11434/v1"
    os.environ["CUSTOM_API_KEY"] = "ollama"
    os.environ["MODEL_PLANNER"] = "custom:llama3.2:latest"
    os.environ["MODEL_EXECUTOR"] = "custom:llama3.2:latest"
    os.environ["MODEL_CRITIC"] = "custom:llama3.2:latest"
    os.environ["MODEL_SYNTHESIZER"] = "custom:llama3.2:latest"
    
    args = argparse.Namespace(
        query="What is the capital of France?",
        fake=False,
        approve=None,
        reject=None,
        feedback=None,
        yes=True,
        session_id="test_session",
        data_dir=".test_data",
        json=False,
        quiet=False,
        depth="balanced"
    )
    
    outcome, session_id = await _drive(args)
    
    print("\n\nSTATUS:", outcome.status)
    if outcome.report:
        print("REPORT LENGTH:", len(outcome.report))
        print("REPORT PREVIEW:", outcome.report[:200])
        print("SUCCESS")
    else:
        print("FAIL:", outcome.error)

if __name__ == "__main__":
    asyncio.run(main())
