"""
Anthropic service integration for HacksterBot.
"""
import os
from pydantic_ai.models.anthropic import AnthropicModel


def get_model(model_name: str) -> AnthropicModel:
    """Get Anthropic model with specified name."""
    return AnthropicModel(model_name, api_key=os.getenv("ANTHROPIC_API_KEY")) 