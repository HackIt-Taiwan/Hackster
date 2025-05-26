"""
Azure OpenAI service integration for HacksterBot.
"""
import os
from openai import AsyncAzureOpenAI
from pydantic_ai.models.openai import OpenAIModel


def get_client():
    """Get Azure OpenAI client."""
    return AsyncAzureOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY")
    )


def get_model(model_name: str) -> OpenAIModel:
    """Get Azure OpenAI model with specified name."""
    # For Azure OpenAI, use the 'azure' provider string
    return OpenAIModel(model_name, provider='azure') 