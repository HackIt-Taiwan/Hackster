"""
Base classes for AI tools.
"""
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.config import Config

logger = logging.getLogger(__name__)


class BaseTool(ABC):
    """
    Base class for all AI tools.
    """
    
    def __init__(self, config: 'Config'):
        """
        Initialize the base tool.
        
        Args:
            config: Configuration object
        """
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name for identification."""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description for AI agents."""
        pass
    
    @property
    def enabled(self) -> bool:
        """Whether this tool is enabled."""
        return True
    
    @abstractmethod
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Execute the tool with given parameters.
        
        Args:
            **kwargs: Tool parameters
            
        Returns:
            Result dictionary with 'success', 'data', and optional 'error' keys
        """
        pass
    
    def get_function_definition(self) -> Dict[str, Any]:
        """
        Get the function definition for pydantic_ai.
        
        Returns:
            Function definition dictionary
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.get_parameters_schema()
        }
    
    @abstractmethod
    def get_parameters_schema(self) -> Dict[str, Any]:
        """
        Get the parameters schema for this tool.
        
        Returns:
            JSON schema for tool parameters
        """
        pass 