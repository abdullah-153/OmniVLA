"""Mock OpenAI client to support hermetic test runs without openai package."""
import requests
import json

class _Choice:
    def __init__(self, content):
        self.message = type("Message", (), {"content": content})()

class _ChatCompletionResponse:
    def __init__(self, content):
        self.choices = [_Choice(content)]

class _Completions:
    def __init__(self, base_url):
        self.base_url = str(base_url).rstrip("/")

    def create(self, model, messages, temperature=0.2, max_tokens=320, response_format=None, **kwargs):
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        if response_format:
            payload["response_format"] = response_format
        resp = requests.post(url, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return _ChatCompletionResponse(content)

class _Chat:
    def __init__(self, base_url):
        self.completions = _Completions(base_url)

class OpenAI:
    def __init__(self, base_url="http://127.0.0.1:8089/v1", api_key="antigravity", **kwargs):
        self.base_url = base_url
        self.api_key = api_key
        self.chat = _Chat(base_url)
