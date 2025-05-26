"""
Base module class for HacksterBot modules.
"""
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .bot import HacksterBot
    from .config import Config


class ModuleBase:
    """
    Base class for bot modules.
    All modules should inherit from this class.
    """
    
    def __init__(self, bot: 'HacksterBot', config: 'Config'):
        """
        Initialize the module.
        
        Args:
            bot: The bot instance
            config: Configuration object
        """
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._initialized = False
    
    async def setup(self) -> None:
        """
        Setup the module. Called when the module is loaded.
        Override this method to implement module-specific setup.
        """
        self.logger.info(f"Setting up module: {self.__class__.__name__}")
        self._initialized = True
    
    async def teardown(self) -> None:
        """
        Teardown the module. Called when the bot is shutting down.
        Override this method to implement module-specific cleanup.
        """
        self.logger.info(f"Tearing down module: {self.__class__.__name__}")
        self._initialized = False
    
    @property
    def is_initialized(self) -> bool:
        """Check if the module is initialized."""
        return self._initialized 