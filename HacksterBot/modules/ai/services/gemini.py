"""
Google Gemini service integration for HacksterBot.
"""
import os
from pydantic_ai.models.gemini import GeminiModel


def get_model(model_name: str) -> GeminiModel:
    """Get Gemini model with specified name."""
    # Ensure GOOGLE_AI_API_KEY environment variable is set
    api_key = os.getenv('GEMINI_API_KEY')
    if api_key:
        os.environ['GOOGLE_AI_API_KEY'] = api_key
    
    return GeminiModel(model_name) 