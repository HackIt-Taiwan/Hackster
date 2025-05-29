"""
Meeting utilities for recording module.
"""

import time
from datetime import datetime


def generate_meeting_room_name() -> str:
    """Generate a unique meeting room name based on current time."""
    current_time = datetime.now()
    return current_time.strftime("Meeting-%m%d-%H%M")


def format_duration(seconds: int) -> str:
    """Format duration in seconds to human readable string."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    
    if hours > 0:
        return f"{hours}小時 {minutes}分鐘 {seconds}秒"
    elif minutes > 0:
        return f"{minutes}分鐘 {seconds}秒"
    else:
        return f"{seconds}秒"


def get_timestamp_string() -> str:
    """Get current timestamp as formatted string."""
    return time.strftime("%Y-%m-%d %H:%M:%S") 