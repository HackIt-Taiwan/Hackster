"""
OpenAI service integration for HacksterBot.
"""
import os
from pydantic_ai.models.openai import OpenAIModel


def get_model(model_name: str) -> OpenAIModel:
    """Get OpenAI model with specified name."""
    return OpenAIModel(model_name, api_key=os.getenv("OPENAI_API_KEY")) 