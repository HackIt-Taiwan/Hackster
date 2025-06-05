"""
Main bot class for HacksterBot.
Handles module loading and Discord bot initialization.
"""
import asyncio
import importlib
import inspect
import logging
import pkgutil
from pathlib import Path
from typing import Dict, List, Optional, Type

import discord
from discord.ext import commands

from .config import Config
from .database import DatabaseManager, create_database_manager
from .mongodb import MongoDBManager, create_mongodb_manager
from .exceptions import BotError, ModuleError
from .module_base import ModuleBase


logger = logging.getLogger(__name__)


class HacksterBot(commands.Bot):
    """
    Main bot class that handles module loading and Discord integration.
    """
    
    def __init__(self, config: Config):
        """
        Initialize the bot.
        
        Args:
            config: Configuration object
        """
        self.config = config
        self.db_manager = create_database_manager(config)
        self.mongodb_manager = create_mongodb_manager(config)
        self.modules: Dict[str, ModuleBase] = {}
        self.logger = logging.getLogger(__name__)
        
        # Setup Discord intents
        intents = discord.Intents.default()
        intents.message_content = config.discord.intents_message_content
        intents.guilds = config.discord.intents_guilds
        intents.members = config.discord.intents_members
        
        # Initialize the bot
        super().__init__(
            command_prefix=config.discord.command_prefix,
            intents=intents,
            help_command=None  # We'll implement our own help command
        )
        
        self.logger.info("HacksterBot initialized")
    
    async def setup_hook(self) -> None:
        """
        Setup hook called when the bot is starting.
        """
        self.logger.info("Running bot setup hook...")
        
        # Sync application commands
        try:
            synced = await self.tree.sync()
            self.logger.info(f"Synced {len(synced)} application commands")
        except Exception as e:
            self.logger.error(f"Failed to sync application commands: {e}")
    
    async def on_ready(self) -> None:
        """
        Event called when the bot is ready.
        """
        self.logger.info(f"Bot is ready! Logged in as {self.user}")
        self.logger.info(f"Connected to {len(self.guilds)} guilds")
        
        # Update bot presence
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name="over HackIt community"
        )
        await self.change_presence(activity=activity, status=discord.Status.online)
    
    async def on_error(self, event: str, *args, **kwargs) -> None:
        """
        Handle bot errors.
        
        Args:
            event: Event name where the error occurred
            *args: Event arguments
            **kwargs: Event keyword arguments
        """
        self.logger.error(f"Error in event {event}", exc_info=True)
    
    async def load_modules(self) -> None:
        """
        Load all modules from the modules directory.
        """
        self.logger.info("Loading modules...")
        
        modules_path = Path(__file__).parent.parent / "modules"
        
        if not modules_path.exists():
            self.logger.warning("Modules directory not found")
            return
        
        # Discover all module packages
        all_modules = []
        for module_info in pkgutil.iter_modules([str(modules_path)]):
            module_name = module_info.name
            
            # Skip modules that are disabled in config
            if not self._is_module_enabled(module_name):
                self.logger.info(f"Module {module_name} is disabled, skipping")
                continue
            
            all_modules.append(module_name)
        
        # Sort modules to ensure critical modules load first
        priority_modules = ['ai', 'tickets_system']  # tickets_system must load before invites
        other_modules = [m for m in all_modules if m not in priority_modules]
        
        # Load priority modules first, then others
        for module_name in priority_modules + other_modules:
            if module_name in all_modules:
                try:
                    await self._load_module(module_name)
                except Exception as e:
                    self.logger.error(f"Failed to load module {module_name}: {e}")
                    if self.config.debug:
                        raise
        
        self.logger.info(f"Loaded {len(self.modules)} modules")
    
    def _is_module_enabled(self, module_name: str) -> bool:
        """
        Check if a module is enabled based on configuration.
        
        Args:
            module_name: Name of the module
            
        Returns:
            True if the module is enabled
        """
        # Map module names to their config enable flags
        module_config_map = {
            'ai': True,  # AI is always enabled
            'moderation': self.config.moderation.enabled,
            'url_safety': self.config.url_safety.enabled,
            'welcome': self.config.welcome.enabled,
            'tickets': self.config.ticket.enabled,
            'tickets_system': True,  # Centralized ticket system is always enabled
            'invites': self.config.invite.enabled,
            'blackjack': True,  # Blackjack game module is enabled by default
            'meetings': self.config.meetings.enabled,  # Meeting scheduling system
            'recording': self.config.recording.enabled,  # Meeting recording system
            'bridge_time': self.config.bridge_time.enabled,  # Meeting time bridge
        }
        
        return module_config_map.get(module_name, True)
    
    async def _load_module(self, module_name: str) -> None:
        """
        Load a specific module.
        
        Args:
            module_name: Name of the module to load
            
        Raises:
            ModuleError: If module loading fails
        """
        try:
            # Import the module
            module_path = f"modules.{module_name}"
            module = importlib.import_module(module_path)
            
            # Look for create_module function first (new format)
            if hasattr(module, 'create_module'):
                # Check if create_module is async
                if inspect.iscoroutinefunction(module.create_module):
                    module_instance = await module.create_module(self, self.config)
                else:
                    module_instance = module.create_module(self, self.config)
                await module_instance.setup()
                self.modules[module_name] = module_instance
                self.logger.info(f"Loaded module: {module_name}")
                
            # Look for setup function or Module class (legacy formats)
            elif hasattr(module, 'setup'):
                # Check if setup function is async
                if inspect.iscoroutinefunction(module.setup):
                    # Async setup function - call directly
                    await module.setup(self, self.config)
                else:
                    # Sync setup function that returns a module instance
                    module_instance = module.setup(self, self.config)
                    if module_instance:
                        await module_instance.setup()
                        self.modules[module_name] = module_instance
                self.logger.info(f"Loaded module: {module_name}")
                
            elif hasattr(module, 'Module'):
                # Module has a Module class
                module_instance = module.Module(self, self.config)
                await module_instance.setup()
                self.modules[module_name] = module_instance
                self.logger.info(f"Loaded module: {module_name}")
                
            else:
                raise ModuleError(f"Module {module_name} has no create_module function, setup function or Module class")
                
        except ImportError as e:
            raise ModuleError(f"Failed to import module {module_name}: {e}")
        except Exception as e:
            raise ModuleError(f"Failed to setup module {module_name}: {e}")
    
    async def unload_module(self, module_name: str) -> None:
        """
        Unload a specific module.
        
        Args:
            module_name: Name of the module to unload
        """
        if module_name in self.modules:
            try:
                await self.modules[module_name].teardown()
                del self.modules[module_name]
                self.logger.info(f"Unloaded module: {module_name}")
            except Exception as e:
                self.logger.error(f"Error unloading module {module_name}: {e}")
        else:
            self.logger.warning(f"Module {module_name} not found")
    
    async def reload_module(self, module_name: str) -> None:
        """
        Reload a specific module.
        
        Args:
            module_name: Name of the module to reload
        """
        await self.unload_module(module_name)
        await self._load_module(module_name)
    
    async def close(self) -> None:
        """
        Close the bot and cleanup resources.
        """
        self.logger.info("Shutting down bot...")
        
        # Teardown all modules
        for module_name, module in self.modules.items():
            try:
                await module.teardown()
            except Exception as e:
                self.logger.error(f"Error during module {module_name} teardown: {e}")
        
        # Close MongoDB connection
        if hasattr(self, 'mongodb_manager') and self.mongodb_manager:
            try:
                self.mongodb_manager.disconnect()
                self.logger.info("MongoDB connection closed")
            except Exception as e:
                self.logger.error(f"Error closing MongoDB connection: {e}")
        
        # Close Discord connection
        await super().close()
        
        self.logger.info("Bot shutdown complete")
    
    def get_module(self, module_name: str) -> Optional[ModuleBase]:
        """
        Get a loaded module by name.
        
        Args:
            module_name: Name of the module
            
        Returns:
            Module instance or None if not found
        """
        return self.modules.get(module_name)
    
    def list_modules(self) -> List[str]:
        """
        Get a list of all loaded module names.
        
        Returns:
            List of module names
        """
        return list(self.modules.keys()) 