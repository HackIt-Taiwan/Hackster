"""
Moderation database management for HacksterBot.
"""
import sqlite3
import logging
import os
import threading
from datetime import datetime, timedelta
from typing import List, Optional, Dict
from contextlib import contextmanager

from config.settings import MODERATION_DB_PATH, MUTE_DURATIONS

logger = logging.getLogger(__name__)


class ModerationDB:
    """Database manager for moderation-related data."""
    
    def __init__(self, db_path: str = MODERATION_DB_PATH):
        """
        Initialize the moderation database.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self.lock = threading.RLock()
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        # Initialize tables
        self.create_tables()
        
    @contextmanager
    def get_connection(self):
        """Get a database connection with automatic cleanup."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row  # Enable dict-like access
        try:
            yield conn
        finally:
            conn.close()
            
    def create_tables(self):
        """Create necessary database tables."""
        with self.lock:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Violations table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS violations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        guild_id INTEGER NOT NULL,
                        content TEXT,
                        violation_categories TEXT,
                        details TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(user_id, guild_id) REFERENCES users(user_id, guild_id)
                    )
                ''')
                
                # Mutes table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS mutes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        guild_id INTEGER NOT NULL,
                        violation_count INTEGER NOT NULL,
                        duration_minutes INTEGER,
                        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        expires_at TIMESTAMP,
                        is_active BOOLEAN DEFAULT 1,
                        deactivated_at TIMESTAMP,
                        FOREIGN KEY(user_id, guild_id) REFERENCES users(user_id, guild_id)
                    )
                ''')
                
                # Users table (for tracking user info)
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER NOT NULL,
                        guild_id INTEGER NOT NULL,
                        username TEXT,
                        first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_violation TIMESTAMP,
                        PRIMARY KEY(user_id, guild_id)
                    )
                ''')
                
                # Create indexes for better performance
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_violations_user_guild ON violations(user_id, guild_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_mutes_user_guild ON mutes(user_id, guild_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_mutes_active ON mutes(is_active)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_mutes_expires ON mutes(expires_at)')
                
                conn.commit()
                
    def add_violation(self, user_id: int, guild_id: int, content: Optional[str] = None, 
                      violation_categories: Optional[List[str]] = None, 
                      details: Optional[Dict] = None) -> int:
        """
        Add a violation record for a user.
        
        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID
            content: Content that caused the violation
            violation_categories: List of violation categories
            details: Additional details about the violation
            
        Returns:
            The ID of the created violation record
        """
        with self.lock:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Ensure user exists
                cursor.execute('''
                    INSERT OR REPLACE INTO users (user_id, guild_id, last_violation)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                ''', (user_id, guild_id))
                
                # Add violation
                violation_categories_str = ','.join(violation_categories) if violation_categories else None
                details_str = str(details) if details else None
                
                cursor.execute('''
                    INSERT INTO violations (user_id, guild_id, content, violation_categories, details)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user_id, guild_id, content, violation_categories_str, details_str))
                
                violation_id = cursor.lastrowid
                conn.commit()
                
                logger.info(f"Added violation record {violation_id} for user {user_id} in guild {guild_id}")
                return violation_id
                
    def get_violation_count(self, user_id: int, guild_id: int) -> int:
        """
        Get the total number of violations for a user in a guild.
        
        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID
            
        Returns:
            Number of violations
        """
        with self.lock:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT COUNT(*) as count FROM violations
                    WHERE user_id = ? AND guild_id = ?
                ''', (user_id, guild_id))
                
                result = cursor.fetchone()
                return result['count'] if result else 0
                
    def add_mute(self, user_id: int, guild_id: int, violation_count: int, 
                duration: Optional[timedelta] = None) -> int:
        """
        Add a mute record for a user.
        
        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID
            violation_count: Current violation count for the user
            duration: Mute duration (if None, calculated from violation count)
            
        Returns:
            The ID of the created mute record
        """
        with self.lock:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Calculate duration if not provided
                if duration is None:
                    duration = self.calculate_mute_duration(violation_count)
                
                # Calculate expiration time
                duration_minutes = None
                expires_at = None
                if duration:
                    duration_minutes = int(duration.total_seconds() / 60)
                    expires_at = datetime.now() + duration
                
                # Add mute record
                cursor.execute('''
                    INSERT INTO mutes (user_id, guild_id, violation_count, duration_minutes, expires_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user_id, guild_id, violation_count, duration_minutes, expires_at))
                
                mute_id = cursor.lastrowid
                conn.commit()
                
                logger.info(f"Added mute record {mute_id} for user {user_id} in guild {guild_id} (duration: {duration})")
                return mute_id
                
    def get_active_mute(self, user_id: int, guild_id: int) -> Optional[Dict]:
        """
        Get the active mute record for a user.
        
        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID
            
        Returns:
            Dict with mute information, or None if no active mute
        """
        with self.lock:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT * FROM mutes
                    WHERE user_id = ? AND guild_id = ? AND is_active = 1
                    ORDER BY started_at DESC
                    LIMIT 1
                ''', (user_id, guild_id))
                
                result = cursor.fetchone()
                if result:
                    return dict(result)
                return None
                
    def _deactivate_mute(self, mute_id: int) -> bool:
        """
        Deactivate a mute record.
        
        Args:
            mute_id: ID of the mute record to deactivate
            
        Returns:
            True if successful, False otherwise
        """
        with self.lock:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    UPDATE mutes 
                    SET is_active = 0, deactivated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (mute_id,))
                
                success = cursor.rowcount > 0
                conn.commit()
                
                if success:
                    logger.info(f"Deactivated mute record {mute_id}")
                
                return success
                
    def check_and_update_expired_mutes(self) -> List[Dict]:
        """
        Check for expired mutes and deactivate them.
        
        Returns:
            List of expired mute records that were deactivated
        """
        with self.lock:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Find expired mutes
                cursor.execute('''
                    SELECT * FROM mutes
                    WHERE is_active = 1 
                    AND expires_at IS NOT NULL 
                    AND expires_at <= CURRENT_TIMESTAMP
                ''')
                
                expired_mutes = [dict(row) for row in cursor.fetchall()]
                
                # Deactivate expired mutes
                for mute in expired_mutes:
                    self._deactivate_mute(mute['id'])
                
                if expired_mutes:
                    logger.info(f"Deactivated {len(expired_mutes)} expired mutes")
                
                return expired_mutes
                
    def calculate_mute_duration(self, violation_count: int) -> Optional[timedelta]:
        """
        Calculate mute duration based on violation count.
        
        Args:
            violation_count: Number of violations for the user
            
        Returns:
            Timedelta for mute duration, or None for permanent
        """
        if violation_count in MUTE_DURATIONS:
            minutes = MUTE_DURATIONS[violation_count]
            return timedelta(minutes=minutes)
        elif violation_count > max(MUTE_DURATIONS.keys()):
            # For violation counts higher than defined, use the highest duration
            minutes = MUTE_DURATIONS[max(MUTE_DURATIONS.keys())]
            return timedelta(minutes=minutes)
        else:
            # For violation count 0 or undefined, no mute
            return None
            
    def close(self):
        """Close database connections and cleanup."""
        # SQLite connections are automatically closed by context manager
        logger.info("Moderation database closed") 