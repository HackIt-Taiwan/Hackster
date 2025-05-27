"""
Configuration package for HacksterBot.
"""

from .logging import setup_logging
from .settings import *

__all__ = [
    "setup_logging",
    "MONGODB_URI",
    "MONGODB_DATABASE"
] 