# -*- coding: utf-8 -*-
"""
Warstwa dostawcy modeli — jedyne miejsce w bots_pro, gdzie wolno wpisać
identyfikator modelu.

Przenośność OpenAI <-> Anthropic jest wymogiem projektu. Realizują ją trzy
zasady; ta pierwsza mieszka tutaj: model jest konfiguracją per rola.
Pozostałe dwie (brak narzędzi hostowanych przez dostawcę, brak funkcji
wyłącznych dla Responses API) pilnują testy inwariantów.

Wartość 'gpt-5.6-terra' idzie do Agents SDK jako string (OpenAI natywnie).
Wartość 'litellm/anthropic/claude-sonnet-5' przechodzi przez adapter LiteLLM.
UWAGA: dokumentacja SDK nazywa adaptery zewnętrzne „best-effort, beta" —
dlatego narzędzia trzymamy neutralne, żeby ewentualny port na tool_runner
Anthropica był mechaniczny.
"""
import os

_PREFIKS_LITELLM = "litellm/"

ROLE_MODELS = {
    "router":     os.environ.get("MODEL_ROUTER", "gpt-5.6-luna"),
    "wycena":     os.environ.get("MODEL_WYCENA", "gpt-5.6-terra"),
    "wiedza":     os.environ.get("MODEL_WIEDZA", "gpt-5.6-terra"),
    "posprzedaz": os.environ.get("MODEL_POSPRZEDAZ", "gpt-5.6-terra"),
    "guardrail":  os.environ.get("MODEL_GUARDRAIL", "gpt-5.6-luna"),
}


def make_model(spec):
    """Identyfikator modelu -> obiekt akceptowany przez Agents SDK."""
    if spec.startswith(_PREFIKS_LITELLM):
        from agents.extensions.models.litellm_model import LitellmModel
        return LitellmModel(
            model=spec[len(_PREFIKS_LITELLM):],
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
        )
    return spec


def model_dla_roli(rola):
    """Model przypisany roli. Nieznana rola to błąd — cicha podmiana na
    domyślny ukryłaby literówkę w konfiguracji."""
    return make_model(ROLE_MODELS[rola])
