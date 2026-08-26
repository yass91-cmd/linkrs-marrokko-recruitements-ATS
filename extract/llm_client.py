import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()  # reads the .env file

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

# A capable free model on OpenRouter (multilingual, good at instructions)
MODEL = "openrouter/free"


if __name__ == "__main__":
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "Reply with exactly: connection OK"}],
    )
    print(response.choices[0].message.content)