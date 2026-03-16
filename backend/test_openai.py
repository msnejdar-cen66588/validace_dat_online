
import asyncio
import os
import httpx
import base64
from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL

async def test_openai():
    print(f"Testing OpenAI gateway: {OPENAI_BASE_URL}")
    print(f"Model: {OPENAI_MODEL}")
    
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Ahoj, jak se máš?"}
        ],
        "max_tokens": 50,
        "temperature": 0.7
    }
    
    verify_ssl = os.getenv("VERIFY_SSL", "true").lower() == "true"
    
    try:
        async with httpx.AsyncClient(timeout=30.0, verify=verify_ssl) as client:
            url = f"{OPENAI_BASE_URL.rstrip('/')}/chat/completions"
            print(f"Request URL: {url}")
            response = await client.post(
                url,
                headers=headers,
                json=payload
            )
            print(f"Status Code: {response.status_code}")
            if response.status_code == 200:
                print("Success!")
                print(f"Response: {response.json()['choices'][0]['message']['content']}")
            else:
                print(f"Error: {response.text}")
    except Exception as e:
        print(f"Exception during request: {e}")

if __name__ == "__main__":
    asyncio.run(test_openai())
