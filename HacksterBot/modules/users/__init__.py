"""User registration module for HacksterBot."""

import logging
import re
import discord
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput, Select

from core.module_base import ModuleBase
from core.exceptions import ModuleError
from core.models import RegisteredUser


logger = logging.getLogger(__name__)


class RegistrationStartView(View):
    """Persistent view with a button to start registration."""

    def __init__(self, module):
        super().__init__(timeout=None)
        self.module = module

    @discord.ui.button(label="Hack Into It！", style=discord.ButtonStyle.primary, custom_id="start_registration")
    async def start(self, interaction: discord.Interaction, button: Button):
        modal = RegistrationModal(self.module)
        await interaction.response.send_modal(modal)


class RegistrationModal(Modal):
    """Modal to collect basic user info."""

    def __init__(self, module):
        super().__init__(title="使用者資料")
        self.module = module
        self.name_input = TextInput(label="真實姓名", required=True)
        self.email_input = TextInput(label="Email", required=True)
        self.source_input = TextInput(label="從哪裡得知我們的 (選填)", required=False)
        self.add_item(self.name_input)
        self.add_item(self.email_input)
        self.add_item(self.source_input)

    async def on_submit(self, interaction: discord.Interaction):
        name = self.name_input.value.strip()
        email = self.email_input.value.strip()
        source = self.source_input.value.strip()

        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            await interaction.response.send_message("Email 格式錯誤，請重新輸入。", ephemeral=True)
            return

        view = EducationSelectView(self.module, name, email, source)
        await interaction.response.send_message("請選擇您的教育階段：", view=view, ephemeral=True)


class EducationSelect(discord.ui.Select):
    """Select menu for education stage."""

    def __init__(self, module, name: str, email: str, source: str):
        options = [
            discord.SelectOption(label="小學", value="小學"),
            discord.SelectOption(label="國中", value="國中"),
            discord.SelectOption(label="高中", value="高中"),
            discord.SelectOption(label="大學以上", value="大學以上"),
        ]
        super().__init__(placeholder="選擇教育階段", options=options)
        self.module = module
        self.name = name
        self.email = email
        self.source = source

    async def callback(self, interaction: discord.Interaction):
        stage = self.values[0]
        view = ConfirmView(self.module, self.name, self.email, self.source, stage)
        embed = discord.Embed(title="歡迎來到 HackIt！", description="babababa")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class EducationSelectView(View):
    def __init__(self, module, name: str, email: str, source: str):
        super().__init__(timeout=180)
        self.add_item(EducationSelect(module, name, email, source))


class ConfirmView(View):
    """Final confirmation view."""

    def __init__(self, module, name: str, email: str, source: str, stage: str):
        super().__init__(timeout=180)
        self.module = module
        self.name = name
        self.email = email
        self.source = source
        self.stage = stage

    @discord.ui.button(label="我已閱讀上述規範，我是乖寶寶，我會遵守！", style=discord.ButtonStyle.success, custom_id="agree_rules")
    async def confirm(self, interaction: discord.Interaction, button: Button):
        role_id = self.module.config.user.registered_role_id
        if role_id:
            role = interaction.guild.get_role(role_id)
            if role:
                try:
                    await interaction.user.add_roles(role, reason="User registration")
                except Exception as e:
                    logger.error(f"Failed to add role: {e}")

        try:
            RegisteredUser.objects(
                user_id=interaction.user.id,
                guild_id=interaction.guild.id
            ).update_one(
                set__real_name=self.name,
                set__email=self.email,
                set__source=self.source,
                set__education_stage=self.stage,
                set_on_insert__registered_at=discord.utils.utcnow(),
                upsert=True,
            )
        except Exception as e:
            logger.error(f"Failed to save registration info: {e}")

        await interaction.response.send_message("註冊完成，感謝你的加入！", ephemeral=True)


class UsersModule(ModuleBase):
    """User registration workflow module."""

    def __init__(self, bot, config):
        super().__init__(bot, config)
        self.name = "users"
        self.description = "User registration and role assignment"

    async def setup(self):
        try:
            if not self.config.user.enabled:
                logger.info("User module is disabled")
                return

            self.bot.add_view(RegistrationStartView(self))

            @self.bot.tree.command(name="registration_panel", description="發送註冊面板 (管理員)")
            @app_commands.checks.has_permissions(administrator=True)
            async def registration_panel(interaction: discord.Interaction):
                view = RegistrationStartView(self)
                embed = discord.Embed(title="Hack Into It！")
                await interaction.channel.send(embed=embed, view=view)
                await interaction.response.send_message("已發送註冊面板", ephemeral=True)

            logger.info("Users module setup completed")
        except Exception as e:
            logger.error(f"Failed to setup users module: {e}")
            raise ModuleError(f"Users module setup failed: {e}")

    async def teardown(self):
        try:
            self.bot.tree.remove_command("registration_panel")
        except Exception:
            pass
        await super().teardown()


async def setup(bot, config):
    module = UsersModule(bot, config)
    await module.setup()
    bot.modules['users'] = module
