"""
Daily reporter for invite system.
Handles scheduled daily reports with growth charts and leaderboards.
"""
import logging
import asyncio
import discord
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Any
from pathlib import Path
import json
import pytz
from io import BytesIO
import math

from core.models import InviteRecord, InviteStatistics, EventTicket

logger = logging.getLogger(__name__)


class DailyReporter:
    """Manages daily reports for invite system."""
    
    def __init__(self, config, invite_mongo, bot):
        """
        Initialize daily reporter.
        
        Args:
            config: Bot configuration
            invite_mongo: Invite MongoDB service
            bot: Discord bot instance
        """
        self.config = config
        self.invite_mongo = invite_mongo
        self.bot = bot
        self.report_config = {}
        
        # Set up Chinese font for matplotlib
        self._setup_matplotlib()
    
    def _setup_matplotlib(self):
        """Set up matplotlib for modern chart rendering."""
        try:
            # Configure matplotlib for modern design with Chinese support
            plt.rcParams['font.family'] = 'sans-serif'
            plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'Segoe UI', 'Arial', 'Helvetica', 'DejaVu Sans']
            plt.rcParams['font.size'] = 11
            plt.rcParams['axes.unicode_minus'] = False
            plt.rcParams['figure.facecolor'] = '#ffffff'
            plt.rcParams['axes.facecolor'] = '#ffffff'
            plt.rcParams['axes.edgecolor'] = 'none'
            plt.rcParams['axes.linewidth'] = 0
            plt.rcParams['axes.spines.top'] = False
            plt.rcParams['axes.spines.right'] = False
            plt.rcParams['axes.spines.left'] = False
            plt.rcParams['axes.spines.bottom'] = False
            plt.rcParams['xtick.bottom'] = False
            plt.rcParams['ytick.left'] = False
            plt.rcParams['grid.linewidth'] = 0.8
            plt.rcParams['grid.alpha'] = 0.2
        except Exception as e:
            logger.warning(f"Could not configure fonts for matplotlib: {e}")
    
    def load_report_config(self) -> bool:
        """
        Load daily report configuration from events config.
        
        Returns:
            bool: True if loaded successfully
        """
        try:
            config_file = Path(self.config.invite.events_config_file)
            
            if not config_file.exists():
                logger.warning(f"Events config file not found: {config_file}")
                return False
            
            with open(config_file, 'r', encoding='utf-8') as f:
                events_config = json.load(f)
            
            self.report_config = events_config.get('daily_reports', {})
            return True
            
        except Exception as e:
            logger.error(f"Error loading report config: {e}")
            return False
    
    def is_enabled(self) -> bool:
        """Check if daily reports are enabled."""
        return self.report_config.get('enabled', False)
    
    def get_schedule_time(self) -> Optional[str]:
        """Get the scheduled time for daily reports."""
        schedule = self.report_config.get('schedule', {})
        return schedule.get('time')
    
    def get_timezone(self) -> str:
        """Get the timezone for daily reports."""
        schedule = self.report_config.get('schedule', {})
        return schedule.get('timezone', 'Asia/Taipei')
    
    def get_channel_id(self) -> Optional[int]:
        """Get the channel ID for daily reports."""
        return self.report_config.get('channel_id')
    
    async def generate_growth_chart(self, guild_id: int, days: int = 30) -> Optional[BytesIO]:
        """
        Generate Discord server growth chart based on active event duration.
        
        Args:
            guild_id: Guild ID
            days: Number of days to show (deprecated, now uses event dates)
            
        Returns:
            BytesIO: Chart image as bytes, or None if no active event
        """
        try:
            # Load events configuration to get active event dates
            config_file = Path(self.config.invite.events_config_file)
            if not config_file.exists():
                logger.warning(f"Events config file not found: {config_file}")
                return None
            
            with open(config_file, 'r', encoding='utf-8') as f:
                events_config = json.load(f)
            
            # Find active event
            active_events = events_config.get('active_events', [])
            if not active_events:
                logger.warning("No active events found")
                return None
            
            # Use the first active event for date range
            active_event = active_events[0]
            start_date_str = active_event.get('start_date')
            end_date_str = active_event.get('end_date')
            
            if not start_date_str or not end_date_str:
                logger.warning("Event missing start_date or end_date")
                return None
            
            # Parse dates
            from datetime import datetime, date
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            today = datetime.utcnow().date()
            
            # Check if event has ended
            if today > end_date:
                logger.info("Event has ended, not generating growth chart")
                return None
            
            # Set actual end date to today if event is still running
            actual_end_date = min(today, end_date)
            
            # Calculate total days for the chart
            total_days = (actual_end_date - start_date).days + 1
            
            logger.info(f"Generating chart from {start_date} to {actual_end_date} ({total_days} days)")
            
            # Get daily member counts (cumulative server member count)
            daily_counts = []
            dates = []
            
            # Get the bot's guild to access current member count
            guild = self.bot.get_guild(guild_id)
            current_member_count = guild.member_count if guild else 0
            
            current_date = start_date
            while current_date <= actual_end_date:
                # Calculate days ago from today
                days_ago = (actual_end_date - current_date).days
                
                # Estimate historical member count
                # Use current count minus recent joins since that date
                recent_joins = InviteRecord.objects(
                    guild_id=guild_id,
                    joined_at__gte=datetime.combine(current_date, datetime.min.time()),
                    is_active=True
                ).count()
                
                estimated_count = max(0, current_member_count - recent_joins)
                if current_date == actual_end_date:
                    estimated_count = current_member_count
                
                daily_counts.append(estimated_count)
                dates.append(current_date)
                current_date += timedelta(days=1)
            
            # Ensure the counts are monotonically increasing (server growth)
            for i in range(1, len(daily_counts)):
                if daily_counts[i] < daily_counts[i-1]:
                    daily_counts[i] = daily_counts[i-1]
            
            if not daily_counts:
                logger.warning("No data available for growth chart")
                return None
            
            # Create modern, beautiful chart with more space for title
            fig, ax = plt.subplots(figsize=(16, 10))
            fig.patch.set_facecolor('#ffffff')
            
            # Chart configuration with modern colors
            chart_config = self.report_config.get('features', {}).get('growth_chart', {})
            primary_color = '#6366f1'  # Modern indigo
            secondary_color = '#a855f7'  # Modern purple
            accent_color = '#06b6d4'  # Modern cyan
            
            # Create smooth line using interpolation for better visual appeal
            try:
                from scipy.interpolate import make_interp_spline
                import numpy as np
                
                # Convert dates to numbers for interpolation
                date_nums = mdates.date2num(dates)
                
                if len(date_nums) >= 2:  # Even with 2 points, create smooth curve
                    if len(date_nums) == 2:
                        # Special handling for 2 points - create artificial curve
                        start_date, end_date = date_nums
                        start_count, end_count = daily_counts
                        
                        # Create intermediate control points for smooth curve
                        mid_date = (start_date + end_date) / 2
                        mid_count = (start_count + end_count) / 2
                        
                        # Add slight curve by adjusting middle point
                        curve_factor = abs(end_count - start_count) * 0.1 + 1
                        mid_count_upper = mid_count + curve_factor
                        
                        # Create extended point array with curves
                        extended_dates = [
                            start_date,
                            start_date + (end_date - start_date) * 0.25,
                            mid_date,
                            start_date + (end_date - start_date) * 0.75,
                            end_date
                        ]
                        extended_counts = [
                            start_count,
                            start_count + (mid_count_upper - start_count) * 0.7,
                            mid_count_upper,
                            end_count - (end_count - mid_count_upper) * 0.7,
                            end_count
                        ]
                        
                        # Create ultra-smooth curve with many points
                        smooth_points = 1000
                        date_smooth = np.linspace(start_date, end_date, smooth_points)
                        spl = make_interp_spline(extended_dates, extended_counts, k=3)
                        counts_smooth = spl(date_smooth)
                        
                    else:
                        # Original logic for 3+ points
                        smooth_points = max(1000, len(date_nums) * 50)
                        date_smooth = np.linspace(date_nums.min(), date_nums.max(), smooth_points)
                        spl = make_interp_spline(date_nums, daily_counts, k=min(3, len(date_nums)-1))
                        counts_smooth = spl(date_smooth)
                    
                    # Convert back to dates
                    dates_smooth = mdates.num2date(date_smooth)
                    
                    # Create ultra-smooth gradient effect
                    for i in range(len(dates_smooth)-1):
                        alpha = 0.6 + 0.4 * (i / len(dates_smooth))
                        ax.plot(dates_smooth[i:i+2], counts_smooth[i:i+2], 
                               color=primary_color, linewidth=2.5, alpha=alpha)
                    
                    # Add elegant fill with gradient
                    ax.fill_between(dates_smooth, counts_smooth, 
                                   alpha=0.15, color=primary_color)
                    
                    # Add subtle shadow effect
                    shadow_offset = (max(counts_smooth) - min(counts_smooth)) * 0.02
                    ax.fill_between(dates_smooth, 
                                   [c - shadow_offset for c in counts_smooth], 
                                   alpha=0.05, color='#1e293b')
                    
                else:
                    # Single point fallback
                    ax.plot(dates, daily_counts, color=primary_color, linewidth=2.5, alpha=0.9)
                    ax.fill_between(dates, daily_counts, alpha=0.15, color=primary_color)
                    
            except ImportError:
                # Enhanced fallback with manual smoothing
                logger.warning("scipy not available, using enhanced manual smoothing")
            
            # Modern clean background
            ax.set_facecolor('#ffffff')
            
            # Stylish title - moved higher outside the chart area
            title = chart_config.get('chart_title', 'Discord 伺服器成長')
            ax.text(0.5, 1.08, title, transform=ax.transAxes, 
                   fontsize=28, fontweight='300', color='#1e293b',
                   ha='center', va='top')
            
            # Subtitle - also moved higher
            event_name = active_event.get('name', '活動期間')
            ax.text(0.5, 1.03, f'{event_name} - 伺服器人數趨勢', transform=ax.transAxes,
                   fontsize=14, fontweight='300', color='#64748b',
                   ha='center', va='top')
            
            # Remove traditional axis labels and use subtle annotations
            ax.set_xlabel('')
            ax.set_ylabel('')
            
            # Custom tick styling - force integer values on Y-axis
            ax.tick_params(axis='both', which='major', labelsize=11, 
                          colors='#64748b', pad=10)
            ax.tick_params(axis='both', which='minor', labelsize=9, colors='#94a3b8')
            
            # Force Y-axis to show only integers
            from matplotlib.ticker import MaxNLocator
            ax.yaxis.set_major_locator(MaxNLocator(integer=True))
            
            # Optimize Y-axis range to make growth more visible
            if daily_counts:
                min_count = min(daily_counts)
                max_count = max(daily_counts)
                count_range = max_count - min_count
                
                # If there's growth, adjust Y-axis to emphasize it
                if count_range > 0:
                    # Add 10% padding below minimum and above maximum
                    padding = max(count_range * 0.1, 1)  # At least 1 unit padding
                    y_min = max(0, min_count - padding)  # Don't go below 0
                    y_max = max_count + padding
                    
                    ax.set_ylim(y_min, y_max)
                else:
                    # If no growth, show flat line with minimal Y-axis range
                    center = daily_counts[0]
                    padding = max(center * 0.02, 2)  # Minimal padding to show flat line
                    ax.set_ylim(center - padding, center + padding)
            
            ax.tick_params(axis='both', which='major', labelsize=11, colors='#64748b', pad=10)
            
            # Format x-axis with better spacing based on total days
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
            if total_days <= 7:
                ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
            elif total_days <= 14:
                ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
            elif total_days <= 30:
                ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, total_days//6)))
            else:
                ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, total_days//8)))
            
            plt.xticks(rotation=0)
            
            # Ultra-subtle grid
            ax.grid(True, alpha=0.1, color='#cbd5e1', linestyle='-', linewidth=0.5)
            ax.set_axisbelow(True)
            
            # Remove branding text - commented out
            # ax.text(0.99, 0.02, 'HacksterBot 數據分析', transform=ax.transAxes,
            #        fontsize=9, fontweight='300', color='#94a3b8',
            #        ha='right', va='bottom', alpha=0.7)
            
            # Clean layout with more top space for title
            plt.tight_layout(pad=3.0)
            plt.subplots_adjust(top=0.8, bottom=0.1, left=0.05, right=0.95)  # More top space
            
            # Save with ultra-high quality
            buffer = BytesIO()
            plt.savefig(buffer, format='png', dpi=300, bbox_inches='tight',
                       facecolor='#ffffff', edgecolor='none', pad_inches=0.3)  # More padding
            buffer.seek(0)
            plt.close()
            
            return buffer
            
        except Exception as e:
            logger.error(f"Error generating growth chart: {e}")
            return None
    
    async def _generate_simple_chart_event_based(self, guild_id: int) -> Optional[BytesIO]:
        """Generate simple chart without scipy interpolation, based on event dates."""
        try:
            # Load events configuration to get active event dates
            config_file = Path(self.config.invite.events_config_file)
            if not config_file.exists():
                logger.warning(f"Events config file not found: {config_file}")
                return None
            
            with open(config_file, 'r', encoding='utf-8') as f:
                events_config = json.load(f)
            
            # Find active event
            active_events = events_config.get('active_events', [])
            if not active_events:
                logger.warning("No active events found")
                return None
            
            # Use the first active event for date range
            active_event = active_events[0]
            start_date_str = active_event.get('start_date')
            end_date_str = active_event.get('end_date')
            
            if not start_date_str or not end_date_str:
                logger.warning("Event missing start_date or end_date")
                return None
            
            # Parse dates
            from datetime import datetime, date
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            today = datetime.utcnow().date()
            
            # Check if event has ended
            if today > end_date:
                logger.info("Event has ended, not generating simple chart")
                return None
            
            # Set actual end date to today if event is still running
            actual_end_date = min(today, end_date)
            
            # Calculate total days for the chart
            total_days = (actual_end_date - start_date).days + 1
            
            # Get daily member counts (cumulative server member count)
            daily_counts = []
            dates = []
            
            # Get the bot's guild to access current member count
            guild = self.bot.get_guild(guild_id)
            current_member_count = guild.member_count if guild else 0
            
            current_date = start_date
            while current_date <= actual_end_date:
                # Calculate days ago from today
                days_ago = (actual_end_date - current_date).days
                
                # Estimate historical member count
                recent_joins = InviteRecord.objects(
                    guild_id=guild_id,
                    joined_at__gte=datetime.combine(current_date, datetime.min.time()),
                    is_active=True
                ).count()
                
                estimated_count = max(0, current_member_count - recent_joins)
                if current_date == actual_end_date:
                    estimated_count = current_member_count
                
                daily_counts.append(estimated_count)
                dates.append(current_date)
                current_date += timedelta(days=1)
            
            # Ensure the counts are monotonically increasing
            for i in range(1, len(daily_counts)):
                if daily_counts[i] < daily_counts[i-1]:
                    daily_counts[i] = daily_counts[i-1]
            
            if not daily_counts:
                return None
            
            # Create modern chart with more space for title
            fig, ax = plt.subplots(figsize=(16, 10))
            fig.patch.set_facecolor('#ffffff')
            
            primary_color = '#6366f1'
            
            # Plot enhanced smooth line - use manual smoothing for better curves
            if len(dates) >= 2:  # Handle even 2 points
                if len(dates) == 2:
                    # Special curve creation for 2 points
                    start_date, end_date = dates
                    start_count, end_count = daily_counts
                    
                    # Create artificial curve by adding intermediate control points
                    total_days = (end_date - start_date).days
                    curve_intensity = max(0.5, abs(end_count - start_count) * 0.05)
                    
                    # Generate curve points
                    extended_dates = []
                    extended_counts = []
                    
                    # Create 20 intermediate points with sine wave curve
                    for i in range(21):  # 0 to 20, inclusive
                        t = i / 20.0  # 0 to 1
                        
                        # Linear interpolation
                        date_point = start_date + timedelta(days=total_days * t)
                        linear_count = start_count + (end_count - start_count) * t
                        
                        # Add sine wave curve for smoothness
                        sine_offset = math.sin(t * math.pi) * curve_intensity
                        curved_count = linear_count + sine_offset
                        
                        extended_dates.append(date_point)
                        extended_counts.append(curved_count)
                    
                    # Apply additional smoothing
                    window_size = 5
                    smoothed_counts = []
                    for i in range(len(extended_counts)):
                        start_idx = max(0, i - window_size // 2)
                        end_idx = min(len(extended_counts), i + window_size // 2 + 1)
                        avg = sum(extended_counts[start_idx:end_idx]) / (end_idx - start_idx)
                        smoothed_counts.append(avg)
                    
                    ax.plot(extended_dates, smoothed_counts, color=primary_color, linewidth=2.5, alpha=0.9)
                    ax.fill_between(extended_dates, smoothed_counts, alpha=0.15, color=primary_color)
                    
                elif len(dates) >= 3:
                    # Original manual smoothing for 3+ points
                    extended_dates = []
                    extended_counts = []
                    
                    for i in range(len(dates) - 1):
                        # Add original point
                        extended_dates.append(dates[i])
                        extended_counts.append(daily_counts[i])
                        
                        # Add intermediate points for smoothness
                        for j in range(1, 8):  # Add 7 intermediate points for extra smoothness
                            fraction = j / 8.0
                            intermediate_date = dates[i] + timedelta(days=fraction)
                            # Use cubic interpolation for smooth transitions
                            t = fraction
                            # Cubic bezier-like interpolation
                            intermediate_count = (daily_counts[i] * (1-t)**3 + 
                                                daily_counts[i] * 3 * (1-t)**2 * t +
                                                daily_counts[i+1] * 3 * (1-t) * t**2 +
                                                daily_counts[i+1] * t**3)
                            extended_dates.append(intermediate_date)
                            extended_counts.append(intermediate_count)
                    
                    # Add final point
                    extended_dates.append(dates[-1])
                    extended_counts.append(daily_counts[-1])
                    
                    # Apply gentle moving average for additional smoothness
                    window_size = min(15, len(extended_counts) // 4)
                    if window_size >= 5:
                        smoothed_counts = []
                        for i in range(len(extended_counts)):
                            start_idx = max(0, i - window_size // 2)
                            end_idx = min(len(extended_counts), i + window_size // 2 + 1)
                            # Weighted average with more weight on center
                            weights = []
                            values = []
                            for j in range(start_idx, end_idx):
                                distance = abs(j - i)
                                weight = max(0.1, 1.0 - distance / (window_size // 2 + 1))
                                weights.append(weight)
                                values.append(extended_counts[j])
                            
                            weighted_avg = sum(v * w for v, w in zip(values, weights)) / sum(weights)
                            smoothed_counts.append(weighted_avg)
                        extended_counts = smoothed_counts
                    
                    ax.plot(extended_dates, extended_counts, color=primary_color, linewidth=2.5, alpha=0.9)
                    ax.fill_between(extended_dates, extended_counts, alpha=0.15, color=primary_color)
            else:
                # Single point fallback
                ax.plot(dates, daily_counts, color=primary_color, linewidth=2.5, alpha=0.9)
                ax.fill_between(dates, daily_counts, alpha=0.15, color=primary_color)
            
            # Apply same modern styling
            ax.set_facecolor('#ffffff')
            
            # Title - moved higher outside the chart area
            title = 'Discord 伺服器成長'
            ax.text(0.5, 1.08, title, transform=ax.transAxes, 
                   fontsize=28, fontweight='300', color='#1e293b',
                   ha='center', va='top')
            
            # Subtitle - also moved higher
            event_name = active_event.get('name', '活動期間')
            ax.text(0.5, 1.03, f'{event_name} - 伺服器人數趨勢', transform=ax.transAxes,
                   fontsize=14, fontweight='300', color='#64748b',
                   ha='center', va='top')
            
            ax.set_xlabel('')
            ax.set_ylabel('')
            
            # Force integer Y-axis
            from matplotlib.ticker import MaxNLocator
            ax.yaxis.set_major_locator(MaxNLocator(integer=True))
            
            # Optimize Y-axis range to make growth more visible
            if daily_counts:
                min_count = min(daily_counts)
                max_count = max(daily_counts)
                count_range = max_count - min_count
                
                # If there's growth, adjust Y-axis to emphasize it
                if count_range > 0:
                    # Add 10% padding below minimum and above maximum
                    padding = max(count_range * 0.1, 1)  # At least 1 unit padding
                    y_min = max(0, min_count - padding)  # Don't go below 0
                    y_max = max_count + padding
                    
                    ax.set_ylim(y_min, y_max)
                else:
                    # If no growth, show flat line with minimal Y-axis range
                    center = daily_counts[0]
                    padding = max(center * 0.02, 2)  # Minimal padding to show flat line
                    ax.set_ylim(center - padding, center + padding)
            
            ax.tick_params(axis='both', which='major', labelsize=11, colors='#64748b', pad=10)
            
            # Format x-axis with better spacing based on total days
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
            
            # Format x-axis with better spacing based on total days
            if total_days <= 7:
                ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
            elif total_days <= 14:
                ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
            elif total_days <= 30:
                ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, total_days//6)))
            else:
                ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, total_days//8)))
            
            plt.xticks(rotation=0)
            
            ax.grid(True, alpha=0.1, color='#cbd5e1', linestyle='-', linewidth=0.5)
            ax.set_axisbelow(True)
            
            # Remove branding text - commented out
            # ax.text(0.99, 0.02, 'HacksterBot 數據分析', transform=ax.transAxes,
            #        fontsize=9, fontweight='300', color='#94a3b8',
            #        ha='right', va='bottom', alpha=0.7)
            
            # Clean layout with more top space for title
            plt.tight_layout(pad=3.0)
            plt.subplots_adjust(top=0.8, bottom=0.1, left=0.05, right=0.95)  # More top space
            
            buffer = BytesIO()
            plt.savefig(buffer, format='png', dpi=300, bbox_inches='tight',
                       facecolor='#ffffff', edgecolor='none', pad_inches=0.3)  # More padding
            buffer.seek(0)
            plt.close()
            
            return buffer
            
        except Exception as e:
            logger.error(f"Error generating simple event-based chart: {e}")
            return None
    
    async def generate_leaderboard_embed(self, guild_id: int, top_count: int = 10) -> discord.Embed:
        """
        Generate ambassador leaderboard embed for past 7 days with daily changes.
        
        Args:
            guild_id: Guild ID
            top_count: Number of top users to show
            
        Returns:
            discord.Embed: Leaderboard embed
        """
        try:
            # Get leaderboard config
            leaderboard_config = self.report_config.get('features', {}).get('leaderboard', {})
            title = leaderboard_config.get('title', '🏆 鄰里大使排行榜')
            show_tickets = leaderboard_config.get('show_tickets', True)
            
            # Use GMT+8 timezone
            gmt8 = pytz.timezone('Asia/Taipei')
            now_gmt8 = datetime.now(gmt8)
            today_start_gmt8 = now_gmt8.replace(hour=0, minute=0, second=0, microsecond=0)
            today_start_utc = today_start_gmt8.astimezone(pytz.utc).replace(tzinfo=None)
            
            # Calculate 7 days ago from today (GMT+8)
            seven_days_ago_gmt8 = today_start_gmt8 - timedelta(days=7)
            seven_days_ago_utc = seven_days_ago_gmt8.astimezone(pytz.utc).replace(tzinfo=None)
            
            # Get yesterday for comparison
            yesterday_start_gmt8 = today_start_gmt8 - timedelta(days=1)
            yesterday_start_utc = yesterday_start_gmt8.astimezone(pytz.utc).replace(tzinfo=None)
            
            # Create embed with modern design
            embed = discord.Embed(
                title=f"{title} (過去7天)",
                color=0x6366f1,  # Modern indigo
                timestamp=datetime.utcnow()
            )
            
            # Get past 7 days invites
            past_7_days_pipeline = [
                {"$match": {
                    "guild_id": guild_id, 
                    "is_active": True,
                    "joined_at": {"$gte": seven_days_ago_utc}
                }},
                {"$group": {
                    "_id": "$inviter_id",
                    "invite_count_7d": {"$sum": 1}
                }},
                {"$sort": {"invite_count_7d": -1}},
                {"$limit": top_count}
            ]
            
            past_7_days_users = list(InviteRecord.objects.aggregate(past_7_days_pipeline))
            
            if not past_7_days_users:
                embed.description = "過去7天還沒有邀請記錄"
                return embed
            
            # Get today's invites for change calculation
            today_pipeline = [
                {"$match": {
                    "guild_id": guild_id, 
                    "is_active": True,
                    "joined_at": {"$gte": today_start_utc}
                }},
                {"$group": {
                    "_id": "$inviter_id",
                    "today_invites": {"$sum": 1}
                }}
            ]
            
            today_users = {user['_id']: user['today_invites'] for user in InviteRecord.objects.aggregate(today_pipeline)}
            
            # Get yesterday's invites for change calculation
            yesterday_pipeline = [
                {"$match": {
                    "guild_id": guild_id, 
                    "is_active": True,
                    "joined_at": {
                        "$gte": yesterday_start_utc,
                        "$lt": today_start_utc
                    }
                }},
                {"$group": {
                    "_id": "$inviter_id",
                    "yesterday_invites": {"$sum": 1}
                }}
            ]
            
            yesterday_users = {user['_id']: user['yesterday_invites'] for user in InviteRecord.objects.aggregate(yesterday_pipeline)}
            
            # Build leaderboard
            leaderboard_text = ""
            medals = ["🥇", "🥈", "🥉"]
            
            for i, user_data in enumerate(past_7_days_users):
                user_id = user_data['_id']
                invite_count_7d = user_data['invite_count_7d']
                
                # Get medal or number
                if i < 3:
                    position = medals[i]
                else:
                    position = f"`{i+1}.`"
                
                # Calculate daily change
                today_count = today_users.get(user_id, 0)
                yesterday_count = yesterday_users.get(user_id, 0)
                daily_change = today_count - yesterday_count
                
                # Format daily change indicator
                if daily_change > 0:
                    change_indicator = f" `(+{daily_change})`"
                elif daily_change < 0:
                    change_indicator = f" `({daily_change})`"
                else:
                    change_indicator = " `(=)`"
                
                # Get ticket count if enabled
                ticket_info = ""
                if show_tickets:
                    from core.models import EventTicket
                    ticket_count = EventTicket.objects(user_id=user_id).count()
                    ticket_info = f" • 🎫 **{ticket_count}**"
                
                # Clean, minimal formatting
                leaderboard_text += f"{position} <@{user_id}> **{invite_count_7d}**{change_indicator}{ticket_info}\n"
            
            embed.description = leaderboard_text
            
            # Add clean footer with GMT+8 time
            time_str = now_gmt8.strftime('%Y-%m-%d %H:%M GMT+8')
            embed.set_footer(text=f"過去7天活躍邀請")
            
            return embed
            
        except Exception as e:
            logger.error(f"Error generating leaderboard embed: {e}")
            # Return error embed
            embed = discord.Embed(
                title="❌ 排行榜生成錯誤",
                description="無法生成排行榜，請稍後再試",
                color=0xff4444
            )
            return embed
    
    async def send_daily_report(self, guild_id: int) -> bool:
        """
        Send daily report to configured channel.
        
        Args:
            guild_id: Guild ID
            
        Returns:
            bool: True if sent successfully
        """
        try:
            if not self.is_enabled():
                return False
            
            channel_id = self.get_channel_id()
            if not channel_id:
                logger.warning("No channel configured for daily reports")
                return False
            
            channel = self.bot.get_channel(channel_id)
            if not channel:
                logger.error(f"Channel {channel_id} not found")
                return False
            
            # Load current config
            if not self.load_report_config():
                return False
            
            content_config = self.report_config.get('content', {})
            features_config = self.report_config.get('features', {})
            
            # Use GMT+8 timezone for report timestamp
            gmt8 = pytz.timezone('Asia/Taipei')
            now_gmt8 = datetime.now(gmt8)
            
            # Create main embed
            embed = discord.Embed(
                title=content_config.get('title', '📊 每日伺服器報告'),
                description=content_config.get('description', '以下是伺服器成長統計和鄰里大使排行榜'),
                color=0x3498db,
                timestamp=datetime.utcnow()
            )
            
            files = []
            
            # Generate growth chart if enabled
            if features_config.get('growth_chart', {}).get('enabled', True):
                chart_buffer = await self.generate_growth_chart(guild_id)
                if chart_buffer:
                    chart_file = discord.File(chart_buffer, filename='growth_chart.png')
                    files.append(chart_file)
                    embed.set_image(url='attachment://growth_chart.png')
            
            # Send main message
            await channel.send(embed=embed, files=files)
            
            # Generate and send leaderboard if enabled
            if features_config.get('leaderboard', {}).get('enabled', True):
                leaderboard_config = features_config.get('leaderboard', {})
                top_count = leaderboard_config.get('top_count', 10)
                
                leaderboard_embed = await self.generate_leaderboard_embed(guild_id, top_count)
                if leaderboard_embed:
                    await channel.send(embed=leaderboard_embed)
            
            logger.info(f"Daily report sent to channel {channel_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending daily report: {e}")
            return False
    
    def get_next_report_time(self) -> Optional[datetime]:
        """
        Get the next scheduled report time.
        
        Returns:
            datetime: Next report time in UTC
        """
        try:
            schedule_time = self.get_schedule_time()
            timezone_name = self.get_timezone()
            
            if not schedule_time:
                return None
            
            # Parse time (HH:MM format)
            hour, minute = map(int, schedule_time.split(':'))
            
            # Get timezone
            tz = pytz.timezone(timezone_name)
            
            # Get current time in the specified timezone
            now = datetime.now(tz)
            
            # Calculate next report time
            next_report = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            # If the time has already passed today, schedule for tomorrow
            if next_report <= now:
                next_report += timedelta(days=1)
            
            # Convert to UTC
            return next_report.astimezone(timezone.utc).replace(tzinfo=None)
            
        except Exception as e:
            logger.error(f"Error calculating next report time: {e}")
            return None 