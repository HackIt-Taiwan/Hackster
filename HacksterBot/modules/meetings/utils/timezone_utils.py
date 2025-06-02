"""
Timezone utilities for meeting system.
"""
from datetime import datetime
from typing import Optional
import pytz


def localize_datetime(dt: datetime, timezone_str: str = "Asia/Taipei") -> datetime:
    """
    Convert a naive datetime to timezone-aware datetime.
    
    Args:
        dt: Naive datetime object
        timezone_str: Timezone string (default: Asia/Taipei for GMT+8)
        
    Returns:
        Timezone-aware datetime
    """
    if dt.tzinfo is not None:
        # Already timezone-aware, convert to target timezone
        tz = pytz.timezone(timezone_str)
        return dt.astimezone(tz)
    else:
        # Naive datetime, localize to target timezone
        tz = pytz.timezone(timezone_str)
        return tz.localize(dt)


def format_datetime_gmt8(dt: datetime, format_str: str = "%Y/%m/%d %H:%M") -> str:
    """
    Format datetime to string with GMT+8 timezone.
    
    Args:
        dt: Datetime object (naive or timezone-aware)
        format_str: Format string for strftime
        
    Returns:
        Formatted datetime string in GMT+8
    """
    # Convert to GMT+8
    gmt8_dt = localize_datetime(dt, "Asia/Taipei")
    return gmt8_dt.strftime(format_str)


def get_current_time_gmt8() -> datetime:
    """
    Get current time in GMT+8 timezone.
    
    Returns:
        Current datetime in GMT+8 timezone
    """
    tz = pytz.timezone("Asia/Taipei")
    return datetime.now(tz)


def naive_to_gmt8(dt: datetime) -> datetime:
    """
    Convert naive datetime to GMT+8 timezone-aware datetime.
    Assumes the naive datetime is already in GMT+8.
    
    Args:
        dt: Naive datetime object
        
    Returns:
        GMT+8 timezone-aware datetime
    """
    if dt.tzinfo is not None:
        return dt.astimezone(pytz.timezone("Asia/Taipei"))
    else:
        tz = pytz.timezone("Asia/Taipei")
        return tz.localize(dt) 