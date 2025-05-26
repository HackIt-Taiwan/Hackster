"""
Google Gemini service integration for HacksterBot.
"""
import os
from pydantic_ai.models.gemini import GeminiModel


def get_model(model_name: str) -> GeminiModel:
    """Get Gemini model with specified name."""
    return GeminiModel(model_name) 