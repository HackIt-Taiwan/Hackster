"""
Invites Module for HacksterBot.

This module provides invite tracking and management capabilities including:
- Creating permanent invite links
- Tracking invite usage statistics
- Managing invite permissions
- Recording invite history
"""
import logging
import sqlite3
import discord
from discord.ext import commands
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
import pytz

from core.module_base import ModuleBase
from core.exceptions import ModuleError
from config.settings import INVITE_DB_PATH, INVITE_EXPIRY_DAYS, MAX_INVITES_PER_USER

logger = logging.getLogger(__name__)


class InviteDB:
    """Database manager for invite tracking."""
    
    def __init__(self, db_path: str = INVITE_DB_PATH):
        """Initialize the invite database."""
        self.db_path = db_path
        self.timezone = pytz.timezone('Asia/Taipei')
        self._ensure_table()
    
    def _ensure_table(self):
        """Ensure the invites table exists."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS invites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    invite_code TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    creator_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1,
                    max_uses INTEGER DEFAULT 0,
                    current_uses INTEGER DEFAULT 0
                )
            """)
            conn.commit()
    
    def add_invite(self, invite_code: str, name: str, creator_id: int, guild_id: int, 
                   channel_id: int, max_uses: int = 0, expires_at: Optional[datetime] = None) -> bool:
        """Add a new invite record."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO invites (invite_code, name, creator_id, guild_id, channel_id, max_uses, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (invite_code, name, creator_id, guild_id, channel_id, max_uses, expires_at))
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            logger.warning(f"Invite code {invite_code} already exists")
            return False
        except Exception as e:
            logger.error(f"Error adding invite record: {e}")
            return False
    
    def update_invite_usage(self, invite_code: str, current_uses: int) -> bool:
        """Update invite usage count."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    UPDATE invites SET current_uses = ? WHERE invite_code = ?
                """, (current_uses, invite_code))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating invite usage: {e}")
            return False
    
    def delete_invite(self, invite_code: str, user_id: Optional[int] = None) -> bool:
        """Delete an invite record."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                if user_id:
                    # Only allow creator to delete their own invites
                    cursor = conn.execute("""
                        UPDATE invites SET is_active = 0 
                        WHERE invite_code = ? AND creator_id = ?
                    """, (invite_code, user_id))
                else:
                    # Admin delete
                    cursor = conn.execute("""
                        UPDATE invites SET is_active = 0 WHERE invite_code = ?
                    """, (invite_code,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting invite: {e}")
            return False
    
    def get_invites_page(self, page: int, page_size: int = 10, guild_id: Optional[int] = None) -> Tuple[List[Dict], int]:
        """Get paginated invite records."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                
                # Build query
                base_query = "SELECT * FROM invites WHERE is_active = 1"
                count_query = "SELECT COUNT(*) FROM invites WHERE is_active = 1"
                params = []
                
                if guild_id:
                    base_query += " AND guild_id = ?"
                    count_query += " AND guild_id = ?"
                    params.append(guild_id)
                
                # Get total count
                cursor = conn.execute(count_query, params)
                total_count = cursor.fetchone()[0]
                
                # Calculate pagination
                total_pages = (total_count + page_size - 1) // page_size
                page = max(1, min(page, total_pages))
                offset = (page - 1) * page_size
                
                # Get paginated results
                query = base_query + " ORDER BY created_at DESC LIMIT ? OFFSET ?"
                cursor = conn.execute(query, params + [page_size, offset])
                
                invites = []
                for row in cursor:
                    # Convert timestamp to local timezone
                    created_at = datetime.strptime(row['created_at'], '%Y-%m-%d %H:%M:%S')
                    created_at = pytz.utc.localize(created_at).astimezone(self.timezone)
                    
                    invites.append({
                        'id': row['id'],
                        'invite_code': row['invite_code'],
                        'name': row['name'],
                        'creator_id': row['creator_id'],
                        'guild_id': row['guild_id'],
                        'channel_id': row['channel_id'],
                        'created_at': created_at,
                        'max_uses': row['max_uses'],
                        'current_uses': row['current_uses'],
                        'is_active': row['is_active']
                    })
                
                return invites, total_pages
                
        except Exception as e:
            logger.error(f"Error getting invites page: {e}")
            return [], 0
    
    def get_user_invite_count(self, user_id: int, guild_id: int) -> int:
        """Get the number of active invites for a user."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT COUNT(*) FROM invites 
                    WHERE creator_id = ? AND guild_id = ? AND is_active = 1
                """, (user_id, guild_id))
                return cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"Error getting user invite count: {e}")
            return 0


class InvitesModule(ModuleBase):
    """Invites module for tracking and managing invite links."""
    
    def __init__(self, bot, config):
        """
        Initialize the invites module.
        
        Args:
            bot: The Discord bot instance
            config: Configuration object
        """
        super().__init__(bot, config)
        self.name = "invites"
        self.description = "Invite tracking and management"
        
        # Initialize database
        self.db = InviteDB()
        
        # Cache for guild invite snapshots
        self.invite_snapshots = {}
        
    async def setup(self):
        """Set up the invites module."""
        try:
            if not self.config.invite.enabled:
                logger.info("Invites module is disabled")
                return
            
            # Take initial invite snapshots for all guilds
            await self._initialize_invite_snapshots()
            
            # Register slash commands
            self.bot.tree.add_command(self.create_invite)
            self.bot.tree.add_command(self.list_invites)
            self.bot.tree.add_command(self.delete_invite)
            
            # Register event listeners
            self.bot.add_listener(self.on_member_join, 'on_member_join')
            self.bot.add_listener(self.on_invite_create, 'on_invite_create')
            self.bot.add_listener(self.on_invite_delete, 'on_invite_delete')
            
            logger.info("Invites module setup completed")
            
        except Exception as e:
            logger.error(f"Failed to setup invites module: {e}")
            raise ModuleError(f"Invites module setup failed: {e}")
    
    async def teardown(self):
        """Clean up the invites module."""
        try:
            # Remove slash commands
            self.bot.tree.remove_command("create_invite")
            self.bot.tree.remove_command("list_invites")
            self.bot.tree.remove_command("delete_invite")
            
            # Remove event listeners
            self.bot.remove_listener(self.on_member_join, 'on_member_join')
            self.bot.remove_listener(self.on_invite_create, 'on_invite_create')
            self.bot.remove_listener(self.on_invite_delete, 'on_invite_delete')
            
            logger.info("Invites module teardown completed")
            
        except Exception as e:
            logger.error(f"Error during invites module teardown: {e}")
    
    async def _initialize_invite_snapshots(self):
        """Initialize invite snapshots for all guilds."""
        for guild in self.bot.guilds:
            try:
                invites = await guild.invites()
                self.invite_snapshots[guild.id] = {invite.code: invite.uses for invite in invites}
                logger.info(f"Initialized invite snapshot for guild {guild.id} with {len(invites)} invites")
            except discord.Forbidden:
                logger.warning(f"No permission to access invites in guild {guild.id}")
            except Exception as e:
                logger.error(f"Error initializing invite snapshot for guild {guild.id}: {e}")
    
    async def on_member_join(self, member: discord.Member):
        """Track which invite was used when a member joins."""
        if not self.config.invite.enabled:
            return
            
        try:
            # Get current invites
            current_invites = await member.guild.invites()
            current_snapshot = {invite.code: invite.uses for invite in current_invites}
            
            # Compare with previous snapshot
            previous_snapshot = self.invite_snapshots.get(member.guild.id, {})
            
            # Find which invite was used
            used_invite = None
            for code, uses in current_snapshot.items():
                if code in previous_snapshot and uses > previous_snapshot[code]:
                    used_invite = code
                    break
                elif code not in previous_snapshot:
                    # New invite was created and used
                    used_invite = code
                    break
            
            # Update usage in database
            if used_invite:
                self.db.update_invite_usage(used_invite, current_snapshot[used_invite])
                logger.info(f"Member {member.id} joined using invite {used_invite}")
            
            # Update snapshot
            self.invite_snapshots[member.guild.id] = current_snapshot
            
        except Exception as e:
            logger.error(f"Error tracking invite usage for member {member.id}: {e}")
    
    async def on_invite_create(self, invite: discord.Invite):
        """Handle invite creation events."""
        if not self.config.invite.enabled:
            return
            
        try:
            # Update snapshot
            guild_id = invite.guild.id
            if guild_id not in self.invite_snapshots:
                self.invite_snapshots[guild_id] = {}
            self.invite_snapshots[guild_id][invite.code] = invite.uses or 0
            
            logger.info(f"Invite {invite.code} created in guild {guild_id}")
            
        except Exception as e:
            logger.error(f"Error handling invite creation: {e}")
    
    async def on_invite_delete(self, invite: discord.Invite):
        """Handle invite deletion events."""
        if not self.config.invite.enabled:
            return
            
        try:
            # Remove from snapshot
            guild_id = invite.guild.id
            if guild_id in self.invite_snapshots:
                self.invite_snapshots[guild_id].pop(invite.code, None)
            
            # Mark as inactive in database
            self.db.delete_invite(invite.code)
            
            logger.info(f"Invite {invite.code} deleted from guild {guild_id}")
            
        except Exception as e:
            logger.error(f"Error handling invite deletion: {e}")
    
    @discord.app_commands.command(name="create_invite", description="創建永久邀請連結")
    @discord.app_commands.describe(name="邀請連結的名稱（用於追蹤統計）")
    async def create_invite(self, interaction: discord.Interaction, name: str):
        """Create a permanent invite link."""
        # Check permissions
        if not any(role.id in self.config.invite.allowed_roles for role in interaction.user.roles):
            await interaction.response.send_message("❌ 您沒有權限創建邀請連結", ephemeral=True)
            return
        
        # Check user's invite limit
        current_count = self.db.get_user_invite_count(interaction.user.id, interaction.guild.id)
        if current_count >= MAX_INVITES_PER_USER:
            await interaction.response.send_message(
                f"❌ 您已達到邀請連結上限 ({MAX_INVITES_PER_USER} 個)", 
                ephemeral=True
            )
            return
        
        try:
            # Get target channel (default to system channel or first text channel)
            target_channel = interaction.guild.system_channel
            if not target_channel:
                target_channel = next((ch for ch in interaction.guild.text_channels if ch.permissions_for(interaction.guild.me).create_instant_invite), None)
            
            if not target_channel:
                await interaction.response.send_message("❌ 無法找到適合的頻道來創建邀請", ephemeral=True)
                return
            
            # Create permanent invite
            invite = await target_channel.create_invite(
                max_age=0,  # Never expires
                max_uses=0,  # Unlimited uses
                unique=True  # Create unique invite
            )
            
            # Record in database
            success = self.db.add_invite(
                invite_code=invite.code,
                name=name,
                creator_id=interaction.user.id,
                guild_id=interaction.guild.id,
                channel_id=target_channel.id
            )
            
            if success:
                # Update snapshot
                if interaction.guild.id not in self.invite_snapshots:
                    self.invite_snapshots[interaction.guild.id] = {}
                self.invite_snapshots[interaction.guild.id][invite.code] = 0
                
                embed = discord.Embed(
                    title="✅ 邀請連結創建成功",
                    color=discord.Color.green()
                )
                embed.add_field(name="名稱", value=name, inline=True)
                embed.add_field(name="連結", value=invite.url, inline=True)
                embed.add_field(name="創建者", value=interaction.user.mention, inline=True)
                embed.set_footer(text="此邀請連結永不過期且無使用次數限制")
                
                await interaction.response.send_message(embed=embed, ephemeral=False)
                logger.info(f"User {interaction.user.id} created invite {invite.code} with name '{name}'")
            else:
                await interaction.response.send_message("❌ 記錄邀請連結時發生錯誤", ephemeral=True)
                
        except discord.Forbidden:
            await interaction.response.send_message("❌ 機器人沒有創建邀請的權限", ephemeral=True)
        except Exception as e:
            logger.error(f"Error creating invite: {e}")
            await interaction.response.send_message("❌ 創建邀請連結時發生錯誤", ephemeral=True)
    
    @discord.app_commands.command(name="list_invites", description="查看邀請連結使用統計")
    @discord.app_commands.describe(page="頁碼（從1開始）")
    async def list_invites(self, interaction: discord.Interaction, page: int = 1):
        """List invite usage statistics."""
        # Check permissions
        if not any(role.id in self.config.invite.allowed_roles for role in interaction.user.roles):
            await interaction.response.send_message("❌ 您沒有權限查看邀請統計", ephemeral=True)
            return
        
        try:
            invites, total_pages = self.db.get_invites_page(page, guild_id=interaction.guild.id)
            
            if not invites:
                await interaction.response.send_message("📊 目前還沒有任何邀請記錄", ephemeral=True)
                return
            
            embed = discord.Embed(
                title="📊 邀請連結使用統計",
                description=f"第 {page}/{total_pages} 頁",
                color=discord.Color.blue()
            )
            
            for invite in invites:
                creator = interaction.guild.get_member(invite['creator_id'])
                creator_name = creator.display_name if creator else "未知用戶"
                
                field_value = (
                    f"**連結：** discord.gg/{invite['invite_code']}\n"
                    f"**使用次數：** {invite['current_uses']} 次\n"
                    f"**創建者：** {creator_name}\n"
                    f"**創建時間：** {invite['created_at'].strftime('%Y-%m-%d %H:%M')}"
                )
                
                embed.add_field(
                    name=f"📎 {invite['name']}",
                    value=field_value,
                    inline=False
                )
            
            if total_pages > 1:
                embed.set_footer(text=f"使用 /list_invites page:<頁碼> 查看其他頁面")
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error listing invites: {e}")
            await interaction.response.send_message("❌ 獲取邀請統計時發生錯誤", ephemeral=True)
    
    @discord.app_commands.command(name="delete_invite", description="刪除邀請連結")
    @discord.app_commands.describe(invite_code="邀請連結的代碼（不是完整URL）")
    async def delete_invite(self, interaction: discord.Interaction, invite_code: str):
        """Delete an invite link."""
        # Check permissions
        if not any(role.id in self.config.invite.allowed_roles for role in interaction.user.roles):
            await interaction.response.send_message("❌ 您沒有權限刪除邀請連結", ephemeral=True)
            return
        
        try:
            # Delete from database (only allows creator to delete their own invites)
            success = self.db.delete_invite(invite_code, interaction.user.id)
            
            if success:
                # Try to delete from Discord
                try:
                    guild_invites = await interaction.guild.invites()
                    for invite in guild_invites:
                        if invite.code == invite_code:
                            await invite.delete()
                            break
                except discord.NotFound:
                    pass  # Invite already deleted
                except discord.Forbidden:
                    logger.warning(f"No permission to delete invite {invite_code} from Discord")
                
                # Update snapshot
                if interaction.guild.id in self.invite_snapshots:
                    self.invite_snapshots[interaction.guild.id].pop(invite_code, None)
                
                await interaction.response.send_message(f"✅ 已成功刪除邀請連結：{invite_code}")
                logger.info(f"User {interaction.user.id} deleted invite {invite_code}")
            else:
                await interaction.response.send_message("❌ 無法刪除邀請連結，可能因為您不是創建者或邀請不存在", ephemeral=True)
                
        except Exception as e:
            logger.error(f"Error deleting invite: {e}")
            await interaction.response.send_message("❌ 刪除邀請連結時發生錯誤", ephemeral=True)


def setup(bot, config):
    """Set up the invites module."""
    return InvitesModule(bot, config) 
