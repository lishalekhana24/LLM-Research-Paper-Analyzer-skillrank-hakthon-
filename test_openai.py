import os
from openai import OpenAI

api_key = os.getenv('OPENAI_API_KEY')
print("API Key from env:", api_key)
client = OpenAI(api_key=api_key)
try:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Say hello!"}]
    )
    print("Success:", response.choices[0].message.content)
except Exception as e:
    print("Error:", e)