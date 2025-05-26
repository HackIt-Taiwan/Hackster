"""
AI service selector for HacksterBot.
Dynamically selects and initializes AI models based on configuration.
"""
import importlib
import logging
from typing import Optional
from pydantic_ai import Agent

from core.config import Config
from ..agents.crazy_talk import create_crazy_agent
from ..agents.general import create_general_agent
from ..agents.classifier import create_classifier_agent
from ..agents.ticket_classifier import create_ticket_classifier_agent

logger = logging.getLogger(__name__)


def ai_select_init(service: str, model: str):
    """
    Initialize an AI model based on service type and model name.
    
    Args:
        service: AI service name (e.g., 'azureopenai', 'gemini', 'openai', 'anthropic')
        model: Model name
        
    Returns:
        AI model instance
        
    Raises:
        ValueError: If service is not supported or model initialization fails
    """
    if not service:
        raise ValueError(f"No such AI service: {service}")

    module_name = f"modules.ai.services.{service}"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as e:
        raise ValueError(f"Module '{module_name}' not found.") from e

    try:
        model_instance = module.get_model(model)
        return model_instance
    except AttributeError as e:
        raise ValueError(f"Module '{module_name}' does not have required methods.") from e


def get_primary_model(config: Config):
    """Get the primary AI model for main AI features."""
    return ai_select_init(config.ai.primary_provider, config.ai.primary_model)


def get_secondary_model(config: Config):
    """Get the secondary AI model for classification and simple tasks."""
    return ai_select_init(config.ai.secondary_provider, config.ai.secondary_model)


# Alias for backward compatibility
def get_classifier_model(config: Config):
    """Get the classifier AI model (uses secondary model)."""
    return get_secondary_model(config)


def get_moderation_review_model(config: Config):
    """Get the AI model for moderation review (uses secondary model)."""
    return get_secondary_model(config)


def get_backup_moderation_review_model(config: Config):
    """Get the backup AI model for moderation review (uses primary model as backup)."""
    try:
        return get_primary_model(config)
    except Exception as e:
        logger.error(f"Error initializing backup moderation review model: {e}")
        return None


async def get_agent(service: str, model: str):
    """
    Get an AI agent for a specific service and model.
    
    Args:
        service: AI service name
        model: Model name
        
    Returns:
        AI agent instance or None if initialization fails
    """
    try:
        return ai_select_init(service, model)
    except Exception as e:
        logger.error(f"Error creating agent for {service}/{model}: {e}")
        return None


async def get_primary_agent(config: Config):
    """Get a primary model agent for a specific service/model."""
    try:
        return get_primary_model(config)
    except Exception as e:
        logger.error(f"Error creating primary agent: {e}")
        return None


async def get_secondary_agent(config: Config):
    """Get a secondary model agent for a specific service/model."""
    try:
        return get_secondary_model(config)
    except Exception as e:
        logger.error(f"Error creating secondary agent: {e}")
        return None


async def create_primary_agent(config: Config) -> Agent:
    """Create the primary agent for main responses."""
    model = get_primary_model(config)
    agent = await create_crazy_agent(model)
    return agent


async def create_general_ai_agent(config: Config) -> Agent:
    """Create a general agent for search responses."""
    model = get_primary_model(config)
    agent = await create_general_agent(model)
    return agent


async def create_message_classifier(config: Config) -> Agent:
    """Create a classifier agent for message classification."""
    model = get_secondary_model(config)  # Use secondary model for classification
    agent = await create_classifier_agent(model)
    return agent


async def create_ticket_classifier(config: Config) -> Agent:
    """Create a classifier agent for ticket classification."""
    model = get_secondary_model(config)  # Use secondary model for classification
    agent = await create_ticket_classifier_agent(model)
    return agent


async def create_moderation_agent(config: Config) -> Agent:
    """Create an agent for moderation tasks."""
    model = get_secondary_model(config)  # Use secondary model for moderation
    agent = await create_general_agent(model)
    return agent


async def create_agent(config: Config, provider: str, model: str):
    """
    Create a generic AI agent for the specified provider and model.
    
    Args:
        config: Configuration object
        provider: AI provider name
        model: Model name
        
    Returns:
        AI agent instance or None if creation fails
    """
    try:
        logger.info(f"Creating agent for {provider}/{model}")
        model_instance = ai_select_init(provider, model)
        # Create a general agent with the specified model
        agent = await create_general_agent(model_instance)
        logger.info(f"Successfully created agent for {provider}/{model}")
        return agent
    except Exception as e:
        logger.error(f"Failed to create agent for {provider}/{model}: {e}")
        return None 