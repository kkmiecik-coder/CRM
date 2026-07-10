# -*- coding: utf-8 -*-
# Fasada warstwy LLM: chat() wybiera dostawce wg config.LLM_PROVIDER. Reszta kodu wola tylko chat()
# i nie wie, czy pod spodem jest OpenAI czy Anthropic. parse_json() = wygodny re-export.
from config import LLM_PROVIDER
from llm.openai_provider import chat_openai
from llm.anthropic_provider import chat_anthropic
from llm.base import extract_json as parse_json


def chat(messages, want_json=False, max_tokens=None):
    if LLM_PROVIDER == "anthropic":
        return chat_anthropic(messages, want_json, max_tokens)
    return chat_openai(messages, want_json, max_tokens)
