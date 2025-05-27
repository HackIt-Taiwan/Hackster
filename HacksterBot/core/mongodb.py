"""
MongoDB connection and management for HacksterBot.
Provides MongoEngine-based database operations.
"""
import logging
from typing import Optional
from mongoengine import connect, disconnect
from .exceptions import DatabaseError

logger = logging.getLogger(__name__)


class MongoDBManager:
    """
    MongoDB manager using MongoEngine for object-oriented database operations.
    """
    
    def __init__(self, mongodb_uri: str, database_name: str):
        """
        Initialize the MongoDB manager.
        
        Args:
            mongodb_uri: MongoDB connection URI
            database_name: Database name
        """
        self.mongodb_uri = mongodb_uri
        self.database_name = database_name
        self._connection = None
        
        logger.info(f"MongoDB manager initialized for database: {database_name}")
    
    def connect(self) -> None:
        """
        Connect to MongoDB using MongoEngine.
        
        Raises:
            DatabaseError: If connection fails
        """
        try:
            self._connection = connect(
                db=self.database_name,
                host=self.mongodb_uri,
                alias='default'
            )
            logger.info(f"Successfully connected to MongoDB: {self.database_name}")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise DatabaseError(f"MongoDB connection failed: {e}")
    
    def disconnect(self) -> None:
        """
        Disconnect from MongoDB.
        """
        try:
            disconnect(alias='default')
            self._connection = None
            logger.info("Disconnected from MongoDB")
        except Exception as e:
            logger.error(f"Error disconnecting from MongoDB: {e}")
    
    def get_connection(self):
        """
        Get the current MongoDB connection.
        
        Returns:
            MongoDB connection
        """
        return self._connection
    
    def is_connected(self) -> bool:
        """
        Check if connected to MongoDB.
        
        Returns:
            True if connected, False otherwise
        """
        return self._connection is not None


def create_mongodb_manager(config) -> MongoDBManager:
    """
    Create and configure MongoDB manager from config.
    
    Args:
        config: Configuration object with MongoDB settings
        
    Returns:
        Configured MongoDBManager instance
    """
    mongodb_uri = getattr(config.database, 'mongodb_uri', 'mongodb://localhost:27017/hacksterbot')
    database_name = getattr(config.database, 'mongodb_database', 'hacksterbot')
    
    manager = MongoDBManager(mongodb_uri, database_name)
    manager.connect()
    
    return manager


def get_database():
    """
    Get the default MongoDB database connection.
    This is a convenience function for modules that need database access.
    
    Returns:
        Database connection (for compatibility, returns None as MongoEngine handles connections automatically)
    """
    # MongoEngine handles connections automatically, so we just return None
    # Models can be used directly without needing a database reference
    return None 