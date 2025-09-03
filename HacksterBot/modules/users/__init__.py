"""User registration module for HacksterBot with clean Apple/Muji style design."""

import logging
import re
import discord
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput, Select
import base64
import aiohttp
from typing import Optional

from core.module_base import ModuleBase
from core.models import RegisteredUser
from core.exceptions import ModuleError

logger = logging.getLogger(__name__)

# Clean Apple-inspired colors
COLORS = {
    'primary': 0x007AFF,
    'success': 0x34C759,
    'secondary': 0x8E8E93,
    'background': 0xF2F2F7
}


class RegistrationStartView(View):
    """Clean registration start view."""

    def __init__(self, module):
        super().__init__(timeout=None)
        self.module = module

    @discord.ui.button(
        label="開始註冊", 
        style=discord.ButtonStyle.primary, 
        custom_id="start_registration_clean"
    )
    async def start_registration(self, interaction: discord.Interaction, button: Button):
        # Check existing registration
        existing = RegisteredUser.objects(
            user_id=interaction.user.id,
            guild_id=interaction.guild.id
        ).first()
        
        if existing:
            embed = discord.Embed(
                title="已完成註冊",
                description=f"歡迎回來，{existing.real_name}",
                color=COLORS['success']
            )
            embed.add_field(
                name="註冊資訊",
                value=f"姓名：{existing.real_name}\n階段：{existing.education_stage}",
                inline=False
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        modal = RegistrationModal(self.module)
        await interaction.response.send_modal(modal)


class RegistrationModal(Modal):
    """Clean registration modal."""

    def __init__(self, module):
        super().__init__(title="基本資料")
        self.module = module
        
        self.name_input = TextInput(
            label="真實姓名",
            placeholder="請輸入您的真實姓名",
            required=True,
            max_length=50
        )
        
        self.email_input = TextInput(
            label="Email",
            placeholder="your.email@example.com",
            required=True,
            max_length=100
        )
        
        self.source_input = TextInput(
            label="如何得知我們",
            placeholder="朋友推薦、社群媒體等（選填）",
            required=False,
            max_length=200
        )
        
        self.add_item(self.name_input)
        self.add_item(self.email_input)
        self.add_item(self.source_input)

    async def on_submit(self, interaction: discord.Interaction):
        name = self.name_input.value.strip()
        email = self.email_input.value.strip()
        source = self.source_input.value.strip()

        # Simple email validation
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            await interaction.response.send_message("Email 格式錯誤", ephemeral=True)
            return

        # Check duplicate email
        existing_email = RegisteredUser.objects(
            email=email,
            guild_id=interaction.guild.id
        ).first()
        
        if existing_email and existing_email.user_id != interaction.user.id:
            await interaction.response.send_message("此 Email 已被使用", ephemeral=True)
            return

        view = EducationSelectView(self.module, name, email, source)
        embed = discord.Embed(
            title="選擇教育階段",
            color=COLORS['primary']
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class EducationSelect(discord.ui.Select):
    """Clean education selection."""

    def __init__(self, module, name: str, email: str, source: str):
        options = [
            discord.SelectOption(label="小學", value="小學", emoji="🌱"),
            discord.SelectOption(label="國中", value="國中", emoji="🌿"),
            discord.SelectOption(label="高中", value="高中", emoji="🌳"),
            discord.SelectOption(label="大學以上", value="大學以上", emoji="🎓"),
        ]
        super().__init__(placeholder="選擇您的教育階段", options=options)
        self.module = module
        self.name = name
        self.email = email
        self.source = source

    async def callback(self, interaction: discord.Interaction):
        stage = self.values[0]
        
        embed = discord.Embed(
            title="確認註冊資訊",
            color=COLORS['primary']
        )
        embed.add_field(
            name="個人資訊",
            value=f"姓名：{self.name}\nEmail：{self.email}\n階段：{stage}",
            inline=False
        )
        
        view = ConfirmView(self.module, self.name, self.email, self.source, stage)
        await interaction.response.edit_message(embed=embed, view=view)


class EducationSelectView(View):
    """Clean education selection view."""
    
    def __init__(self, module, name: str, email: str, source: str):
        super().__init__(timeout=300)
        self.add_item(EducationSelect(module, name, email, source))


class ConfirmView(View):
    """Clean confirmation view."""

    def __init__(self, module, name: str, email: str, source: str, stage: str):
        super().__init__(timeout=300)
        self.module = module
        self.name = name
        self.email = email
        self.source = source
        self.stage = stage

    @discord.ui.button(
        label="確認註冊", 
        style=discord.ButtonStyle.success
    )
    async def confirm_registration(self, interaction: discord.Interaction, button: Button):
        try:
            # Download and encode avatar
            avatar_base64 = await self._get_avatar_base64(interaction.user)
            
            # Add role if configured
            role_id = self.module.config.user.registered_role_id
            if role_id:
                role = interaction.guild.get_role(role_id)
                if role:
                    try:
                        await interaction.user.add_roles(role, reason="User registration")
                    except Exception as e:
                        logger.error(f"Failed to add role: {e}")

            # Save to database
            RegisteredUser.objects(
                user_id=interaction.user.id,
                guild_id=interaction.guild.id
            ).update_one(
                set__real_name=self.name,
                set__email=self.email,
                set__source=self.source,
                set__education_stage=self.stage,
                set__avatar_base64=avatar_base64,
                set__registered_at=discord.utils.utcnow(),
                upsert=True,
            )

            embed = discord.Embed(
                title="註冊完成",
                description=f"歡迎加入，{self.name}！",
                color=COLORS['success']
            )
            await interaction.response.edit_message(embed=embed, view=None)
            
        except Exception as e:
            logger.error(f"Registration failed: {e}")
            await interaction.response.send_message("註冊失敗，請稍後重試", ephemeral=True)

    @discord.ui.button(
        label="取消", 
        style=discord.ButtonStyle.secondary
    )
    async def cancel_registration(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(
            title="已取消註冊",
            color=COLORS['secondary']
        )
        await interaction.response.edit_message(embed=embed, view=None)

    async def _get_avatar_base64(self, user: discord.User) -> Optional[str]:
        """Download user avatar and convert to base64."""
        try:
            avatar_url = user.display_avatar.url
            async with aiohttp.ClientSession() as session:
                async with session.get(avatar_url) as response:
                    if response.status == 200:
                        avatar_data = await response.read()
                        return base64.b64encode(avatar_data).decode('utf-8')
        except Exception as e:
            logger.error(f"Failed to download avatar: {e}")
        return None


class UsersModule(ModuleBase):
    """Clean user registration module."""

    def __init__(self, bot, config):
        super().__init__(bot, config)
        self.name = "users"
        self.description = "User registration system"

    async def setup(self):
        try:
            if not self.config.user.enabled:
                logger.info("User module is disabled")
                return

            self.bot.add_view(RegistrationStartView(self))

            @self.bot.tree.command(
                name="registration_panel", 
                description="發送註冊面板"
            )
            @app_commands.checks.has_permissions(administrator=True)
            async def registration_panel(interaction: discord.Interaction):
                view = RegistrationStartView(self)
                
                embed = discord.Embed(
                    title="歡迎加入 HackIt",
                    description="點擊下方按鈕開始註冊",
                    color=COLORS['primary']
                )
                
                await interaction.channel.send(embed=embed, view=view)
                await interaction.response.send_message("✓ 已發送註冊面板", ephemeral=True)

            @self.bot.tree.command(
                name="registration_stats",
                description="查看註冊統計"
            )
            @app_commands.checks.has_permissions(administrator=True)
            async def registration_stats(interaction: discord.Interaction):
                try:
                    total = RegisteredUser.objects(guild_id=interaction.guild.id).count()
                    
                    # Get education distribution
                    pipeline = [
                        {"$match": {"guild_id": interaction.guild.id}},
                        {"$group": {"_id": "$education_stage", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}}
                    ]
                    
                    stage_stats = list(RegisteredUser.objects.aggregate(pipeline))
                    
                    embed = discord.Embed(
                        title="註冊統計",
                        description=f"總註冊人數：{total}",
                        color=COLORS['primary']
                    )
                    
                    if stage_stats:
                        stage_text = "\n".join([
                            f"{stat['_id']}：{stat['count']} 人"
                            for stat in stage_stats
                        ])
                        embed.add_field(
                            name="教育階段分布",
                            value=stage_text,
                            inline=False
                        )
                    
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    
                except Exception as e:
                    logger.error(f"Error generating stats: {e}")
                    await interaction.response.send_message("統計生成失敗", ephemeral=True)

            logger.info("Users module setup completed")
            
        except Exception as e:
            logger.error(f"Failed to setup users module: {e}")
            raise ModuleError(f"Users module setup failed: {e}")

    async def teardown(self):
        try:
            self.bot.tree.remove_command("registration_panel")
            self.bot.tree.remove_command("registration_stats")
        except Exception:
            pass
        await super().teardown()


async def setup(bot, config):
    module = UsersModule(bot, config)
    await module.setup()
    bot.modules['users'] = module
