import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)


async def main():
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "").strip()
    model = os.getenv("OPENAI_MODEL", "").strip()

    if not api_key:
        print("ERROR: OPENAI_API_KEY is missing.")
        return

    print("API key loaded:", True)
    print("Base URL:", repr(base_url))
    print("Model:", repr(model))
    print("Testing OpenRouter connection...")

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=30.0,
        max_retries=0,
    )

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": "Reply with exactly: ReCoverIQ connected",
                }
            ],
            max_tokens=30,
        )

        print("SUCCESS:", response.choices[0].message.content)

    except Exception as exc:
        print("ERROR TYPE:", type(exc).__name__)
        print("ERROR DETAILS:", str(exc))

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())