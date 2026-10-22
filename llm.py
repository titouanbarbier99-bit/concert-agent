"""Point d'appel unique du LLM.

Le meme code fonctionne avec Gemini, OpenAI, OpenRouter, Groq ou Ollama,
car tous exposent une API compatible OpenAI /chat/completions.
Sans cle (et hors Ollama), obtenir_llm() renvoie None : l'application
bascule sur le moteur de regles.
"""

import json
import os

import requests


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self, base_url, api_key, model, provider="openai"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.model = model
        self.provider = provider

    @property
    def label(self):
        return f"{self.provider} / {self.model}"

    def chat(self, messages, tools=None, timeout=60):
        payload = {
            "model": self.model,
            "messages": messages,
        }
        if tools:
            payload["tools"] = [tool.schema_openai() for tool in tools]
            payload["tool_choice"] = "auto"

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key

        try:
            response = requests.post(
                self.base_url + "/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise LLMError(f"LLM injoignable : {exc}") from exc

        if response.status_code >= 400:
            detail = response.text[:400].replace("\n", " ")
            raise LLMError(f"LLM HTTP {response.status_code} : {detail}")

        try:
            data = response.json()
            message = data["choices"][0]["message"]
        except (ValueError, KeyError, IndexError) as exc:
            raise LLMError("Reponse LLM illisible") from exc

        content = message.get("content")
        if isinstance(content, list):
            message["content"] = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )

        if not message.get("tool_calls") and message.get("function_call"):
            message["tool_calls"] = [{
                "id": "call_0",
                "type": "function",
                "function": message["function_call"],
            }]

        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            arguments = function.get("arguments")
            if isinstance(arguments, dict):
                function["arguments"] = json.dumps(arguments, ensure_ascii=False)
            elif arguments is None:
                function["arguments"] = "{}"
            if not call.get("id"):
                call["id"] = "call_" + str(abs(hash(function.get("name", ""))))

        return message


def _provider_config():
    provider = (os.getenv("LLM_PROVIDER") or "gemini").strip().lower()
    model_override = (os.getenv("LLM_MODEL") or "").strip()

    if provider == "ollama":
        return {
            "provider": "ollama",
            "base_url": os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"),
            "api_key": "",
            "model": model_override or "qwen2.5:7b",
        }

    key = (os.getenv("LLM_API_KEY") or "").strip()
    if not key:
        key = (os.getenv("GEMINI_API_KEY") or "").strip() if provider == "gemini" else ""
    if not key:
        return None

    if provider == "gemini":
        return {
            "provider": "gemini",
            "base_url": os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"),
            "api_key": key,
            "model": model_override or "gemini-3.5-flash-lite",
        }
    if provider == "openrouter":
        return {
            "provider": "openrouter",
            "base_url": os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
            "api_key": key,
            "model": model_override or "google/gemini-2.5-flash",
        }
    if provider == "groq":
        return {
            "provider": "groq",
            "base_url": os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
            "api_key": key,
            "model": model_override or "llama-3.3-70b-versatile",
        }
    return {
        "provider": "openai",
        "base_url": os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
        "api_key": key,
        "model": model_override or "gpt-4o-mini",
    }


def obtenir_llm():
    """Retourne un client LLM, ou None si aucune cle n'est configuree."""
    config = _provider_config()
    if not config:
        return None
    return LLMClient(
        config["base_url"],
        config["api_key"],
        config["model"],
        config["provider"],
    )


def etat_llm():
    client = obtenir_llm()
    if not client:
        return {
            "disponible": False,
            "mode": "regles",
            "provider": "",
            "model": "",
            "message": "Aucune cle LLM : moteur de regles actif.",
        }
    return {
        "disponible": True,
        "mode": "llm",
        "provider": client.provider,
        "model": client.model,
        "message": f"LLM actif : {client.label}",
    }
