"""
Database management for HacksterBot.
Provides base classes and utilities for database operations.
"""
import asyncio
import logging
import sqlite3
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .exceptions import DatabaseError


logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Main database manager that handles connections and transactions.
    """
    
    def __init__(self, database_url: str):
        """
        Initialize the database manager.
        
        Args:
            database_url: Database connection URL
        """
        self.database_url = database_url
        self._lock = asyncio.Lock()
        
        # Extract database path for SQLite
        if database_url.startswith('sqlite:///'):
            self.db_path = database_url[10:]  # Remove 'sqlite:///'
            # Create directory if it doesn't exist
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        else:
            self.db_path = None
            
        logger.info(f"Database manager initialized with URL: {database_url}")
    
    @contextmanager
    def get_connection(self):
        """
        Get a database connection context manager.
        
        Yields:
            Connection object
            
        Raises:
            DatabaseError: If connection fails
        """
        if not self.db_path:
            raise DatabaseError("Only SQLite databases are currently supported")
            
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row  # Enable dict-like access
            yield conn
        except sqlite3.Error as e:
            logger.error(f"Database connection error: {e}")
            raise DatabaseError(f"Database connection failed: {e}")
        finally:
            if 'conn' in locals():
                conn.close()
    
    def execute_script(self, script: str) -> None:
        """
        Execute a SQL script.
        
        Args:
            script: SQL script to execute
            
        Raises:
            DatabaseError: If script execution fails
        """
        try:
            with self.get_connection() as conn:
                conn.executescript(script)
                conn.commit()
            logger.info("Database script executed successfully")
        except sqlite3.Error as e:
            logger.error(f"Script execution error: {e}")
            raise DatabaseError(f"Script execution failed: {e}")
    
    async def execute_async(self, query: str, params: Optional[Tuple] = None) -> List[Dict]:
        """
        Execute a query asynchronously.
        
        Args:
            query: SQL query to execute
            params: Query parameters
            
        Returns:
            List of result dictionaries
            
        Raises:
            DatabaseError: If query execution fails
        """
        async with self._lock:
            try:
                with self.get_connection() as conn:
                    cursor = conn.execute(query, params or ())
                    results = [dict(row) for row in cursor.fetchall()]
                    conn.commit()
                    return results
            except sqlite3.Error as e:
                logger.error(f"Async query execution error: {e}")
                raise DatabaseError(f"Query execution failed: {e}")


class BaseModel(ABC):
    """
    Abstract base class for database models.
    """
    
    def __init__(self, db_manager: DatabaseManager):
        """
        Initialize the model.
        
        Args:
            db_manager: Database manager instance
        """
        self.db = db_manager
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    @abstractmethod
    def create_tables(self) -> None:
        """Create the necessary database tables."""
        pass
    
    def execute_query(self, query: str, params: Optional[Tuple] = None, 
                     fetch_one: bool = False) -> Union[List[Dict], Dict, None]:
        """
        Execute a database query.
        
        Args:
            query: SQL query to execute
            params: Query parameters
            fetch_one: Whether to return only the first result
            
        Returns:
            Query results
            
        Raises:
            DatabaseError: If query execution fails
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute(query, params or ())
                
                if fetch_one:
                    row = cursor.fetchone()
                    result = dict(row) if row else None
                else:
                    result = [dict(row) for row in cursor.fetchall()]
                
                conn.commit()
                return result
                
        except sqlite3.Error as e:
            self.logger.error(f"Query execution error: {e}")
            raise DatabaseError(f"Database query failed: {e}")
    
    def insert_record(self, table: str, data: Dict[str, Any]) -> int:
        """
        Insert a record into the database.
        
        Args:
            table: Table name
            data: Record data
            
        Returns:
            ID of the inserted record
            
        Raises:
            DatabaseError: If insertion fails
        """
        columns = ', '.join(data.keys())
        placeholders = ', '.join(['?' for _ in data])
        query = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute(query, tuple(data.values()))
                conn.commit()
                return cursor.lastrowid
                
        except sqlite3.Error as e:
            self.logger.error(f"Insert error: {e}")
            raise DatabaseError(f"Record insertion failed: {e}")
    
    def update_record(self, table: str, data: Dict[str, Any], 
                     where_clause: str, where_params: Tuple) -> int:
        """
        Update records in the database.
        
        Args:
            table: Table name
            data: Data to update
            where_clause: WHERE clause
            where_params: WHERE clause parameters
            
        Returns:
            Number of affected rows
            
        Raises:
            DatabaseError: If update fails
        """
        set_clause = ', '.join([f"{k} = ?" for k in data.keys()])
        query = f"UPDATE {table} SET {set_clause} WHERE {where_clause}"
        params = tuple(data.values()) + where_params
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute(query, params)
                conn.commit()
                return cursor.rowcount
                
        except sqlite3.Error as e:
            self.logger.error(f"Update error: {e}")
            raise DatabaseError(f"Record update failed: {e}")
    
    def delete_record(self, table: str, where_clause: str, where_params: Tuple) -> int:
        """
        Delete records from the database.
        
        Args:
            table: Table name
            where_clause: WHERE clause
            where_params: WHERE clause parameters
            
        Returns:
            Number of affected rows
            
        Raises:
            DatabaseError: If deletion fails
        """
        query = f"DELETE FROM {table} WHERE {where_clause}"
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute(query, where_params)
                conn.commit()
                return cursor.rowcount
                
        except sqlite3.Error as e:
            self.logger.error(f"Delete error: {e}")
            raise DatabaseError(f"Record deletion failed: {e}")


def create_database_manager(config) -> DatabaseManager:
    """
    Create a database manager from configuration.
    
    Args:
        config: Database configuration
        
    Returns:
        DatabaseManager instance
    """
    return DatabaseManager(config.database.url) 