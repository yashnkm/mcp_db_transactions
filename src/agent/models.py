"""Provider-agnostic factories for chat models and embeddings.

Swapping providers is a one-line change in `.env` — no code changes needed.
"""
from __future__ import annotations

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from agent.config import settings


def build_chat_model(
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
) -> BaseChatModel:
    provider = (provider or settings.llm_provider).lower()
    model = model or settings.llm_model
    temperature = settings.llm_temperature if temperature is None else temperature

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model,
            temperature=temperature,
            api_key=settings.anthropic_api_key,
        )
    if provider in {"google_genai", "google", "gemini"}:
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model,
            temperature=temperature,
            google_api_key=settings.google_api_key,
        )
    raise ValueError(f"Unsupported LLM provider: {provider!r}")


def build_classifier_model() -> BaseChatModel:
    return build_chat_model(
        provider=settings.classifier_provider or settings.llm_provider,
        model=settings.classifier_model or settings.llm_model,
        temperature=0.0,
    )


def build_executor_model() -> BaseChatModel:
    return build_chat_model(
        provider=settings.executor_provider or settings.llm_provider,
        model=settings.executor_model or settings.llm_model,
        temperature=0.0,
    )


def build_embeddings(
    provider: str | None = None,
    model: str | None = None,
) -> Embeddings:
    provider = (provider or settings.embeddings_provider).lower()
    model = model or settings.embeddings_model

    if provider in {"huggingface", "hf", "local"}:
        from langchain_huggingface import HuggingFaceEmbeddings

        return HuggingFaceEmbeddings(
            model_name=model,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
    if provider in {"google_genai", "google", "gemini"}:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        return GoogleGenerativeAIEmbeddings(
            model=f"models/{model}" if not model.startswith("models/") else model,
            google_api_key=settings.google_api_key,
        )
    if provider == "openai":
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(model=model, api_key=settings.openai_api_key)
    raise ValueError(f"Unsupported embeddings provider: {provider!r}")
