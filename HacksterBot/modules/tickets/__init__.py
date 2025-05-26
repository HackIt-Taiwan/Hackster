"""
Tickets Module for HacksterBot - Complete AITicket Port.

This module provides a comprehensive ticket system including:
- AI-powered ticket classification using multiple LLM providers
- Event-specific ticket handling and categorization
- Complete UI workflow identical to original AITicket
- Full conversation logging and transcript generation
- Smart categorization and event matching
- Persistent views and message replacement
"""
import logging
import sqlite3
import discord
from discord.ext import commands, tasks
from discord.ui import Button, View, Select, Modal, TextInput
from typing import List, Optional, Dict, Any, Tuple, Union
from datetime import datetime, timedelta
import asyncio
import os
import time
import json
import io
import re
import chat_exporter

from core.module_base import ModuleBase
from core.exceptions import ModuleError
from config.settings import USER_DATA_PATH, EMBED_COLORS
from modules.ai.services.ai_select import create_ticket_classifier, create_general_ai_agent

logger = logging.getLogger(__name__)


class TicketModal(Modal):
    """Modal for ticket creation - exact copy from AITicket."""
    
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.add_item(TextInput(
            label='請簡述您的需求或問題',
            placeholder="簡單描述您的需求，我們將為您提供專屬的協助。HackIt 團隊期待與您交流！",
            style=discord.TextStyle.paragraph,
            max_length=300
        ))

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user = interaction.user
        guild = interaction.guild
        filepath = f'{USER_DATA_PATH}{str(user.id)}.txt'
        print(
            f"[HackIt Ticket] User {user} attempted to create exclusive conversation channel at {time.strftime('%Y/%m/%d %H:%M')}")
        
        # Get tickets module
        tickets_module = None
        for module in interaction.client.modules.values():
            if hasattr(module, 'name') and module.name == "tickets":
                tickets_module = module
                break
        
        if not tickets_module:
            await interaction.followup.send("❌ 工單系統暫時無法使用", ephemeral=True)
            return

        # Check if user already has a ticket, and if the channel actually exists
        if os.path.isfile(filepath):
            channel_id = await tickets_module.check_ticket_channel_exists(guild, filepath)
            
            if channel_id:
                await interaction.followup.send(
                    content=f"您已經擁有一個對話頻道 <#{channel_id}>！\n若您認為這是個錯誤請直接在公共區域通知我們的團隊成員。", 
                    ephemeral=True)
                return
            else:
                # Channel doesn't exist, but file does, possibly old channel was deleted
                try:
                    os.remove(filepath)
                    print(f"[HackIt Ticket] User {user}'s old ticket file deleted, allowing new ticket creation")
                except Exception as e:
                    print(f"[HackIt Ticket] Failed to delete old ticket file: {e}")

        # Initialize ticket info file, but don't mark as created yet
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write("UserID: " + str(user.id) + "\n")
                f.write("UserName: " + user.display_name + "\n")
                f.write("UserInput: " + self.children[0].value + "\n")
                f.write("TicketCreatedTime: " + time.strftime('%Y/%m/%d %H:%M:%S') + "\n")
                f.write("TicketLogs:\n")
                f.write("* " + time.strftime('%Y/%m/%d %H:%M:%S:') + " - " + "Ticket Processing Started\n")
        except Exception as e:
            print(f"[HackIt Ticket] Failed to create ticket log file: {e}")
            await interaction.followup.send("創建工單時發生錯誤，請稍後再試或聯絡管理員。", ephemeral=True)
            return

        await tickets_module.process_ticket(interaction, user, filepath)


class GenerateTicketView(View):
    """Main ticket generation view with management buttons - exact copy from AITicket."""
    
    def __init__(self, apply: bool):
        super().__init__(timeout=None)
        self.apply = apply

    @discord.ui.button(label="關閉頻道", emoji="📩", custom_id="closeticket", style=discord.ButtonStyle.gray, row=0)
    async def close_ticket(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(thinking=True)
        
        channel = interaction.channel
        topic = channel.topic
        user = interaction.guild.get_member(int(topic)) if topic and topic.isdigit() else None
        
        tickets_module = None
        for module in interaction.client.modules.values():
            if hasattr(module, 'name') and module.name == "tickets":
                tickets_module = module
                break
        
        if tickets_module and user:
            await tickets_module.close_channel(channel, interaction.guild, user)

    @discord.ui.button(label="類別有誤", emoji="⚠️", custom_id="wrong_category", style=discord.ButtonStyle.danger, row=0)
    async def change_category(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(thinking=True)
        
        await interaction.followup.send("正在重新分類工單...", ephemeral=True)
        
        # Clear event-specific permissions since user is changing category
        tickets_module = None
        for module in interaction.client.modules.values():
            if hasattr(module, 'name') and module.name == "tickets":
                tickets_module = module
                break
        
        if tickets_module:
            await tickets_module.clear_event_permissions(interaction.channel, interaction.guild)
        
        today = time.strftime('%Y/%m/%d %H:%M')
        embed = discord.Embed(
            title="選擇新類別",
            description="很抱歉！我們的 AI 自動分類系統目前尚未完善，若分類有誤，請選擇一個正確的分類。HackIt 團隊感謝您的協助和理解！",
            color=0x6366F1
        )
        embed.set_footer(text=f"{today} ● HackIt Team")
        
        category_view = CategorySelectionView()
        
        await interaction.channel.purge()
        await interaction.channel.send(embed=embed, view=category_view)

    @discord.ui.button(label="添加成員", emoji="👥", custom_id="add_member_ticket", style=discord.ButtonStyle.success, row=0)
    async def add_member(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(thinking=True)
        await interaction.followup.send("請選擇要添加到此頻道的成員：", view=MemberSelectView(), ephemeral=True)


class EventTicketView(View):
    """Event-specific ticket view with activity reselection buttons."""
    
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(label="重選活動", emoji="🔄", custom_id="reselect_event_ticket", style=discord.ButtonStyle.primary, row=0)
    async def reselect_event(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ 只有工單創建者可以重新選擇活動", ephemeral=True)
            return
            
        await interaction.response.defer()
        
        tickets_module = None
        for module in interaction.client.modules.values():
            if hasattr(module, 'name') and module.name == "tickets":
                tickets_module = module
                break
        
        if not tickets_module:
            await interaction.followup.send("❌ 工單系統暫時無法使用", ephemeral=True)
            return
        
        select_view = EventSelectView(self.user_id)
        
        today = time.strftime('%Y/%m/%d %H:%M')
        embed = discord.Embed(
            title="請重新選擇相關活動",
            description="請從以下活動中選擇與您問題最相關的活動：",
            color=0x6366F1
        )
        embed.set_footer(text=today + " ● HackIt Team")
        
        await interaction.edit_original_response(embed=embed, view=select_view)

    @discord.ui.button(label="關閉頻道", emoji="📩", custom_id="closeticket_event_ticket", style=discord.ButtonStyle.gray, row=0)
    async def close_ticket(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(thinking=True)
        
        channel = interaction.channel
        topic = channel.topic
        user = interaction.guild.get_member(int(topic)) if topic and topic.isdigit() else None
        
        tickets_module = None
        for module in interaction.client.modules.values():
            if hasattr(module, 'name') and module.name == "tickets":
                tickets_module = module
                break
        
        if tickets_module and user:
            await tickets_module.close_channel(channel, interaction.guild, user)

    @discord.ui.button(label="類別有誤", emoji="⚠️", custom_id="wrong_category_event_ticket", style=discord.ButtonStyle.danger, row=0)
    async def change_category(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(thinking=True)
        
        await interaction.followup.send("正在重新分類工單...", ephemeral=True)
        
        # Clear event-specific permissions since user is changing category
        tickets_module = None
        for module in interaction.client.modules.values():
            if hasattr(module, 'name') and module.name == "tickets":
                tickets_module = module
                break
        
        if tickets_module:
            await tickets_module.clear_event_permissions(interaction.channel, interaction.guild)
        
        today = time.strftime('%Y/%m/%d %H:%M')
        embed = discord.Embed(
            title="選擇新類別",
            description="很抱歉！我們的 AI 自動分類系統目前尚未完善，若分類有誤，請選擇一個正確的分類。HackIt 團隊感謝您的協助和理解！",
            color=0x6366F1
        )
        embed.set_footer(text=f"{today} ● HackIt Team")
        
        category_view = CategorySelectionView()
        
        await interaction.channel.purge()
        await interaction.channel.send(embed=embed, view=category_view)

    @discord.ui.button(label="添加成員", emoji="👥", custom_id="add_member_event_ticket", style=discord.ButtonStyle.success, row=0)
    async def add_member(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(thinking=True)
        await interaction.followup.send("請選擇要添加到此頻道的成員：", view=MemberSelectView(), ephemeral=True)


class EventSelectionView(View):
    """Event selection view for event categorization - exact copy from AITicket."""
    
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(label="活動分類有誤", emoji="🔄", custom_id="select_other_event", style=discord.ButtonStyle.primary, row=0)
    async def select_other_event(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ 只有工單創建者可以重新選擇活動", ephemeral=True)
            return
            
        await interaction.response.defer(thinking=True)
        
        # Delete classification result message
        try:
            async for message in interaction.channel.history(limit=10):
                if message.author.id == interaction.guild.me.id and len(message.embeds) > 0:
                    embed = message.embeds[0]
                    if embed.title and "智能分類結果" in embed.title:
                        await message.delete()
                        break
        except Exception as e:
            logger.error(f"Error deleting classification result message: {e}")
        
        tickets_module = None
        for module in interaction.client.modules.values():
            if hasattr(module, 'name') and module.name == "tickets":
                tickets_module = module
                break
        
        if not tickets_module:
            await interaction.followup.send("❌ 工單系統暫時無法使用", ephemeral=True)
            return
        
        select_view = EventSelectView(self.user_id)
        
        today = time.strftime('%Y/%m/%d %H:%M')
        embed = discord.Embed(
            title="請重新選擇相關活動",
            description="請從以下活動中選擇與您問題最相關的活動：",
            color=0x6366F1
        )
        embed.set_footer(text=today + " ● HackIt Team")
        
        select_message = await interaction.followup.send(embed=embed, view=select_view, ephemeral=False)
        
        # Record in log file
        channel = interaction.channel
        user_id = int(channel.topic) if channel.topic and channel.topic.isdigit() else None
        if user_id:
            filepath = f'{USER_DATA_PATH}{user_id}.txt'
            if os.path.exists(filepath):
                with open(filepath, "a", encoding="utf-8") as f:
                    f.write(f"* {time.strftime('%Y/%m/%d %H:%M:%S:')} - Select Event Message ID: {select_message.id}\n")
                    f.write(f"* {time.strftime('%Y/%m/%d %H:%M:%S:')} - User requested to reselect event\n")

    @discord.ui.button(label="類別分類有誤", emoji="⚠️", custom_id="wrong_category_event", style=discord.ButtonStyle.danger, row=0)
    async def change_category(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(thinking=True)
        await interaction.followup.send("正在重新分類工單...", ephemeral=True)
        
        # Clear event-specific permissions since user is changing category
        tickets_module = None
        for module in interaction.client.modules.values():
            if hasattr(module, 'name') and module.name == "tickets":
                tickets_module = module
                break
        
        if tickets_module:
            await tickets_module.clear_event_permissions(interaction.channel, interaction.guild)
        
        # Delete classification result message
        try:
            async for message in interaction.channel.history(limit=10):
                if message.author.id == interaction.guild.me.id and len(message.embeds) > 0:
                    embed = message.embeds[0]
                    if embed.title and "智能分類結果" in embed.title:
                        await message.delete()
                        break
        except Exception as e:
            logger.error(f"Error deleting classification result message: {e}")
        
        today = time.strftime('%Y/%m/%d %H:%M')
        embed = discord.Embed(
            title="選擇新類別",
            description="很抱歉！我們的 AI 自動分類系統目前尚未完善，若分類有誤，請選擇一個正確的分類。HackIt 團隊感謝您的協助和理解！",
            color=0x6366F1
        )
        embed.set_footer(text=f"{today} ● HackIt Team")
        
        category_view = CategorySelectionView()
        
        await interaction.channel.purge()
        await interaction.channel.send(embed=embed, view=category_view)

    @discord.ui.button(label="關閉頻道", emoji="📩", custom_id="closeticket_event_selection", style=discord.ButtonStyle.gray, row=0)
    async def close_ticket(self, interaction: discord.Interaction, button: Button):
        channel = interaction.channel
        topic = channel.topic
        user = interaction.guild.get_member(int(topic)) if topic and topic.isdigit() else None
        
        tickets_module = None
        for module in interaction.client.modules.values():
            if hasattr(module, 'name') and module.name == "tickets":
                tickets_module = module
                break
        
        if tickets_module and user:
            await tickets_module.close_channel(channel, interaction.guild, user)

    @discord.ui.button(label="添加成員", emoji="👥", custom_id="add_member_event_selection", style=discord.ButtonStyle.success, row=0)
    async def add_member(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(thinking=True)
        await interaction.followup.send("請選擇要添加到此頻道的成員：", view=MemberSelectView(), ephemeral=True)


class EventSelectView(View):
    """Event selection dropdown menu view - exact copy from AITicket."""
    
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = user_id
        
        # Load events config and create select
        self._load_events_and_create_select()
    
    def _load_events_and_create_select(self):
        """Load events from config and create select options."""
        try:
            # Load events config directly since we can't access bot modules from View init
            events_config = self._load_events_config()
            print(f"[DEBUG] EventSelectView - Loaded events config: {events_config}")
            
            active_events = [event for event in events_config["events"] if event.get("active", True)]
            print(f"[DEBUG] EventSelectView - Active events: {len(active_events)} events")
            
            options = []
            for i, event in enumerate(active_events):
                emoji = "🎯" if i == 0 else "🚀" if i == 1 else "💡" if i == 2 else "🔧" if i == 3 else "🎮"
                description = event.get("description", "")[:100]
                
                option = discord.SelectOption(
                    label=event["name"],
                    description=description,
                    value=event["id"],
                    emoji=emoji
                )
                options.append(option)
                print(f"[DEBUG] EventSelectView - Created option: {event['name']} (active: {event.get('active', True)})")
            
            print(f"[DEBUG] EventSelectView - Total options created: {len(options)}")
            
            if options:
                self.event_select = Select(
                    placeholder="請選擇相關活動...",
                    options=options,
                    custom_id="event_select"
                )
                self.event_select.callback = self.select_callback
                self.add_item(self.event_select)
                print(f"[DEBUG] EventSelectView - Successfully added select with {len(options)} options")
            else:
                print(f"[DEBUG] EventSelectView - No options available, not adding select")
        except Exception as e:
            logger.error(f"Failed to load events config: {e}")
            print(f"[DEBUG] EventSelectView - Exception in _load_events_and_create_select: {e}")
    
    def _load_events_config(self):
        """Load events configuration."""
        events_config_path = "data/events.json"
        
        try:
            if os.path.exists(events_config_path):
                with open(events_config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                logger.warning(f"Events configuration file not found: {events_config_path}")
                return {"events": []}
                
        except Exception as e:
            logger.error(f"Error loading events configuration: {e}")
            return {"events": []}

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    async def select_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        selected_event_id = interaction.data['values'][0]
        
        tickets_module = None
        for module in interaction.client.modules.values():
            if hasattr(module, 'name') and module.name == "tickets":
                tickets_module = module
                break
        
        if not tickets_module:
            await interaction.followup.send("❌ 工單系統暫時無法使用", ephemeral=True)
            return
        
        # Find the selected event
        selected_event = None
        for event in tickets_module.events_config["events"]:
            if event["id"] == selected_event_id:
                selected_event = event
                break
        
        if not selected_event:
            await interaction.followup.send("❌ 找不到選擇的活動", ephemeral=True)
            return
        
        # Update channel for event
        await tickets_module.update_channel_for_event(interaction.channel, interaction.guild, selected_event_id)
        
        # Get user's initial question and create final ticket message
        filepath = f'{USER_DATA_PATH}{str(interaction.user.id)}.txt'
        user_initial_input = tickets_module.get_user_input_from_filepath(filepath)
        
        # Determine the category based on context - check which category brought us here
        category = "活動諮詢"  # Default
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in lines:
                    if "Ticket Categorized as" in line:
                        category = line.split("Ticket Categorized as ")[1].strip()
                        break
        except Exception:
            pass
        
        # Get ticket info for the correct category
        title, description, _ = tickets_module.generate_ticket_info(category)
        
        today = time.strftime('%Y/%m/%d %H:%M')
        
        # Create final ticket embed with complete information
        embed = discord.Embed(
            title=title,
            description=description,
            color=0x6366F1
        )
        
        # Add user's initial question if available
        if user_initial_input:
            embed.add_field(
                name="📝 您的問題",
                value=f"「{user_initial_input}」",
                inline=False
            )
            embed.add_field(
                name="💬 後續說明",
                value="請在此頻道中進一步詳細描述您的需求，我們會盡快回覆！",
                inline=False
            )
        
        # Add event selection confirmation
        embed.add_field(
            name="🎯 相關活動",
            value=f"已分類至「**{selected_event['name']}**」活動",
            inline=False
        )
        
        embed.set_footer(text=today + " ● HackIt Team")
        
        # Create event-specific management view with reselect activity button
        final_view = EventTicketView(self.user_id)
        await interaction.edit_original_response(embed=embed, view=final_view)
        
        # Record in log file
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(f"* {time.strftime('%Y/%m/%d %H:%M:%S:')} - Event Selection Finalized: {selected_event['name']}\n")


class CategorySelectionView(View):
    """Category selection view for manual categorization - exact copy from AITicket."""
    
    def __init__(self):
        super().__init__(timeout=None)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        logger.error(f"Error in CategorySelectionView: {error}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ 處理分類選擇時發生錯誤", ephemeral=True)
        except Exception:
            pass

    @discord.ui.select(
        placeholder="請選擇正確分類",
        custom_id="persistent_category_select",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(
                label="活動諮詢",
                emoji="🎯",
                description="關於 HackIt 目前/過去舉辦的活動，包括報名問題等"
            ),
            discord.SelectOption(
                label="提案活動",
                emoji="💡",
                description="向 HackIt 提出你的瘋狂願景，讓我們協助您實現"
            ),
            discord.SelectOption(
                label="加入我們",
                emoji="🚀",
                description="想加入 HackIt 團隊或成為志工"
            ),
            discord.SelectOption(
                label="資源需求",
                emoji="🔧",
                description="尋求技術支援、教學資源、場地或其他資源協助"
            ),
            discord.SelectOption(
                label="贊助合作",
                emoji="🤝",
                description="企業或組織希望與 HackIt 進行贊助或合作"
            ),
            discord.SelectOption(
                label="反饋投訴",
                emoji="📝",
                description="對 HackIt 活動或服務提出反饋或投訴"
            ),
            discord.SelectOption(
                label="其他問題",
                emoji="❓",
                description="任何其他類別的問題或需求"
            )
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: Select):
        await interaction.response.defer()
        
        selected_category = interaction.data['values'][0]
        
        tickets_module = None
        for module in interaction.client.modules.values():
            if hasattr(module, 'name') and module.name == "tickets":
                tickets_module = module
                break
        
        if not tickets_module:
            await interaction.followup.send("❌ 工單系統暫時無法使用", ephemeral=True)
            return
        
        # Check if event categorization is needed
        if selected_category in tickets_module.event_category_types and len(tickets_module.events_config["events"]) > 0:
            # Event categorization needed
            active_events = [event for event in tickets_module.events_config["events"] if event.get("active", True)]
            if active_events:
                # Show event selection - use EventSelectView which contains the dropdown menu
                event_selection_view = EventSelectView(interaction.user.id)
                
                today = time.strftime('%Y/%m/%d %H:%M')
                embed = discord.Embed(
                    title="請選擇相關活動",
                    description=f"您選擇了「**{selected_category}**」類別。\n\n請進一步選擇與您問題最相關的活動：",
                    color=0x6366F1
                )
                embed.set_footer(text=today + " ● HackIt Team")
                
                await interaction.edit_original_response(embed=embed, view=event_selection_view)
                return
        
        # No event categorization needed, finalize ticket by replacing current message
        title, description, allow_role = tickets_module.generate_ticket_info(selected_category)
        
        # Get user's initial question
        filepath = f'{USER_DATA_PATH}{str(interaction.user.id)}.txt'
        user_initial_input = tickets_module.get_user_input_from_filepath(filepath)
        
        today = time.strftime('%Y/%m/%d %H:%M')
        
        # Create final embed with user's initial question
        category_embed = discord.Embed(
            title=title,
            description=description,
            color=0x6366F1
        )
        
        # Add user's initial question if available
        if user_initial_input:
            category_embed.add_field(
                name="📝 您的問題",
                value=f"「{user_initial_input}」",
                inline=False
            )
            category_embed.add_field(
                name="💬 後續說明",
                value="請在此頻道中進一步詳細描述您的需求，我們會盡快回覆！",
                inline=False
            )
        
        category_embed.set_footer(text=today + " ● HackIt Team")
        
        # Determine which view to use based on category type
        if selected_category in tickets_module.event_category_types:
            # This should not normally happen since event categories go to event selection,
            # but adding as fallback for edge cases
            final_view = EventTicketView(interaction.user.id)
        else:
            # Non-event categories use standard view
            final_view = GenerateTicketView(False)
        
        # Replace the selection message with final categorization result
        await interaction.edit_original_response(embed=category_embed, view=final_view)
        
        # Record completion in log
        with open(filepath, "a", encoding="utf-8") as f:
            f.write("* " + time.strftime('%Y/%m/%d %H:%M:%S:') + " - " + "Manual Category Selection Completed\n")


class EventConfirmView(View):
    """Event confirmation view - exact copy from AITicket."""
    
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = user_id

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        logger.error(f"Error in EventConfirmView: {error}")

    @discord.ui.button(label="重選活動", emoji="🔁", custom_id="reselect_event", style=discord.ButtonStyle.primary, row=0)
    async def reselect_event(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ 只有工單創建者可以重新選擇活動", ephemeral=True)
            return
            
        await interaction.response.defer()
        
        tickets_module = None
        for module in interaction.client.modules.values():
            if hasattr(module, 'name') and module.name == "tickets":
                tickets_module = module
                break
        
        if not tickets_module:
            await interaction.followup.send("❌ 工單系統暫時無法使用", ephemeral=True)
            return
        
        select_view = EventSelectView(self.user_id)
        
        today = time.strftime('%Y/%m/%d %H:%M')
        embed = discord.Embed(
            title="請重新選擇相關活動",
            description="請從以下活動中選擇與您問題最相關的活動：",
            color=0x6366F1
        )
        embed.set_footer(text=today + " ● HackIt Team")
        
        await interaction.edit_original_response(embed=embed, view=select_view)

    @discord.ui.button(label="類別分類有誤", emoji="⚠️", custom_id="wrong_category_confirm", style=discord.ButtonStyle.danger, row=0)
    async def change_category(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(thinking=True)
        await interaction.followup.send("正在重新分類工單...", ephemeral=True)
        
        # Clear event-specific permissions since user is changing category
        tickets_module = None
        for module in interaction.client.modules.values():
            if hasattr(module, 'name') and module.name == "tickets":
                tickets_module = module
                break
        
        if tickets_module:
            await tickets_module.clear_event_permissions(interaction.channel, interaction.guild)
        
        today = time.strftime('%Y/%m/%d %H:%M')
        embed = discord.Embed(
            title="選擇新類別",
            description="很抱歉！我們的 AI 自動分類系統目前尚未完善，若分類有誤，請選擇一個正確的分類。HackIt 團隊感謝您的協助和理解！",
            color=0x6366F1
        )
        embed.set_footer(text=f"{today} ● HackIt Team")
        
        category_view = CategorySelectionView()
        
        await interaction.channel.purge()
        await interaction.channel.send(embed=embed, view=category_view)

    @discord.ui.button(label="關閉頻道", emoji="📩", custom_id="close_ticket_confirm_view", style=discord.ButtonStyle.gray, row=0)
    async def close_ticket(self, interaction: discord.Interaction, button: Button):
        channel = interaction.channel
        topic = channel.topic
        user = interaction.guild.get_member(int(topic)) if topic and topic.isdigit() else None
        
        tickets_module = None
        for module in interaction.client.modules.values():
            if hasattr(module, 'name') and module.name == "tickets":
                tickets_module = module
                break
        
        if tickets_module and user:
            await tickets_module.close_channel(channel, interaction.guild, user)

    @discord.ui.button(label="添加成員", emoji="👥", custom_id="add_member_confirm_view", style=discord.ButtonStyle.success, row=0)
    async def add_member(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(thinking=True)
        await interaction.followup.send("請選擇要添加到此頻道的成員：", view=MemberSelectView(), ephemeral=True)


class MemberSelectView(View):
    """Member selection view for adding members to tickets - exact copy from AITicket."""
    
    def __init__(self):
        super().__init__(timeout=None)
        
        # Add user select menu
        self.user_select = discord.ui.UserSelect(
            placeholder="選擇要添加的成員...",
            min_values=1,
            max_values=1,
            custom_id="persistent_user_select"
        )
        self.user_select.callback = self.user_select_callback
        self.add_item(self.user_select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check permissions."""
        # Check if user has permission (staff or ticket creator)
        topic = interaction.channel.topic
        user_id = int(topic) if topic and topic.isdigit() else None
        is_staff = any(role.name in ["Admin", "Moderator", "Staff"] for role in interaction.user.roles)
        return interaction.user.id == user_id or is_staff

    async def user_select_callback(self, interaction: discord.Interaction):
        """Handle user selection."""
        await interaction.response.defer()
        
        selected_user = self.user_select.values[0]
        channel = interaction.channel
        
        try:
            # Add read permission for selected user
            overwrites = channel.overwrites
            overwrites[selected_user] = discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                read_message_history=True
            )
            await channel.edit(overwrites=overwrites)
            
            # Send immediate confirmation
            await interaction.followup.send(f"✅ 已成功將 {selected_user.mention} 添加到此工單頻道", ephemeral=True)
            
            # Send notification in channel
            today = time.strftime('%Y/%m/%d %H:%M')
            embed = discord.Embed(
                title="👥 成員已添加",
                description=f"{selected_user.mention} 已被添加到此對話頻道中，現在可以參與討論。",
                color=0x00ff00
            )
            embed.set_footer(text=f"{today} ● HackIt Team")
            await channel.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error adding member to ticket: {e}")
            await interaction.followup.send("❌ 添加成員時發生錯誤", ephemeral=True)


class GenerateTicket(View):
    """Main ticket generation button - exact copy from AITicket."""
    
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="聯絡 HackIt", emoji="✉️", custom_id="GenerateTicket", style=discord.ButtonStyle.primary)
    async def button_callback(self, interaction: discord.Interaction, button: Button):
        """Handle ticket generation button."""
        if button.custom_id == "GenerateTicket":
            user = interaction.user
            today = time.strftime('%Y/%m/%d %H:%M')
            print(f"[HackIt Ticket] User {user} attempted to create exclusive conversation channel at {today}")
            
            try:
                await interaction.response.send_modal(TicketModal(title="問題簡述"))
            except Exception as e:
                print(f"[HackIt Ticket] Failed to open modal: {e}")
                await interaction.response.defer(thinking=True)
                await interaction.followup.send(content="Opening exclusive conversation channel failed, please try again later.", ephemeral=True)


class TicketsModule(ModuleBase):
    """Complete AITicket port for HacksterBot."""
    
    def __init__(self, bot, config):
        """Initialize the tickets module."""
        super().__init__(bot, config)
        self.name = "tickets"
        self.description = "Complete ticket system with AI classification"
        
        # AI services - will be initialized in setup()
        self._classifier_agent = None
        self._general_agent = None
        
        # Ensure directories exist
        os.makedirs(USER_DATA_PATH, exist_ok=True)
        os.makedirs("data", exist_ok=True)
        
        # Load configuration from environment variables
        self.ticket_customer_id = int(os.getenv("TICKET_CUSTOMER_ID", "1070698736910614559"))
        self.ticket_developer_id = int(os.getenv("TICKET_DEVELOPER_ID", "1070698621030375504"))
        self.ticket_admin_id = int(os.getenv("TICKET_ADMIN_ID", "933349161452044378"))
        self.ticket_log_channel_id = int(os.getenv("TICKET_LOG_CHANNEL_ID", "0"))
        
        # Event category types that require event categorization
        self.event_category_types = ["活動諮詢", "加入我們"]
        
        # Load events configuration
        self.events_config = self._load_events_config()
    
    def _load_events_config(self):
        """Load events configuration from JSON file."""
        events_config_path = "data/events.json"
        
        try:
            if os.path.exists(events_config_path):
                with open(events_config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                logger.warning(f"Events configuration file not found: {events_config_path}")
                return {"events": []}
                
        except Exception as e:
            logger.error(f"Error loading events configuration: {e}")
            return {"events": []}
    
    async def setup(self):
        """Set up the tickets module."""
        try:
            if not self.config.ticket.enabled:
                logger.info("Tickets module is disabled")
                return
            
            # Initialize AI services
            try:
                self._classifier_agent = await create_ticket_classifier(self.config)
                self._general_agent = await create_general_ai_agent(self.config)
                logger.info("AI services initialized for tickets module")
            except Exception as e:
                logger.error(f"Failed to initialize AI services: {e}")
                # Continue setup without AI services
                self._classifier_agent = None
                self._general_agent = None
            
            # Register persistent views
            self.bot.add_view(GenerateTicket())
            self.bot.add_view(GenerateTicketView(False))
            self.bot.add_view(EventTicketView(user_id=0))
            self.bot.add_view(CategorySelectionView())
            self.bot.add_view(EventSelectionView(user_id=0))
            self.bot.add_view(EventSelectView(user_id=0))
            self.bot.add_view(EventConfirmView(user_id=0))
            self.bot.add_view(MemberSelectView())
            
            # Register slash commands
            self.bot.tree.add_command(self.create_ticket_panel)
            self.bot.tree.add_command(self.close_ticket_cmd)
            
            logger.info("Tickets module setup completed")
            
        except Exception as e:
            logger.error(f"Failed to setup tickets module: {e}")
            raise ModuleError(f"Tickets module setup failed: {e}")
    
    async def teardown(self):
        """Clean up the tickets module."""
        try:
            # Remove slash commands
            self.bot.tree.remove_command("create_ticket_panel")
            self.bot.tree.remove_command("close_ticket")
            
            logger.info("Tickets module teardown completed")
            
        except Exception as e:
            logger.error(f"Error during tickets module teardown: {e}")
    
    async def process_ticket(self, interaction: discord.Interaction, user: discord.User, filepath: str):
        """Process ticket creation with complete AI classification matching AITicket."""
        guild = interaction.guild
        kind, provider, e = await self.analyze_user_message(user)
        
        if kind == "Error":
            await interaction.followup.send(
                content="自動分類失敗，已自動分類至「其他問題」\n我們已紀錄本次錯誤，未來將持續改進，造成不便請見諒",
                ephemeral=True)
            logError = f"* {time.strftime('%Y/%m/%d %H:%M:%S:')} - [ERROR] Ticket cannot be categorized automatically\n*-----Error-----* \n{e}\n\n"
            kind = "其他問題"
        else:
            logError = None
        
        with open(filepath, "a", encoding="utf-8") as f:
            if logError:
                f.write(logError)
            f.write(f"* {time.strftime('%Y/%m/%d %H:%M:%S:')} - Ticket Categorized as {kind}\n")
            f.write(f"* {time.strftime('%Y/%m/%d %H:%M:%S:')} - Used LLM Provider: {provider}\n")
        
        # Create channel
        title, description, allowRole = self.generate_ticket_info(kind)
        overwrites = self.get_channel_overwrites(guild, user, allowRole)
        
        try:
            channel = await guild.create_text_channel(
                "對話 - " + str(user.display_name),
                overwrites=overwrites,
                position=0,
                topic=str(user.id)
            )
            
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(f"* {time.strftime('%Y/%m/%d %H:%M:%S:')} - {user.display_name} Created Ticket\n")
                f.write(f"* {time.strftime('%Y/%m/%d %H:%M:%S:')} - Ticket Channel Created: {channel.id}\n")
                
        except Exception as e:
            logger.error(f"Failed to create channel: {e}")
            await interaction.followup.send("創建專屬對話頻道時發生錯誤，請稍後再試或聯絡管理員。", ephemeral=True)
            return
        
        # Check if event categorization is needed
        if kind in self.event_category_types and len(self.events_config["events"]) > 0:
            # Event categorization needed
            await self.process_event_categorization(interaction, user, channel, title, description, kind, filepath)
        else:
            # No event categorization needed
            await self.finalize_ticket_creation(interaction, user, channel, allowRole, title, description, False, kind)
        
        return channel
    
    async def process_event_categorization(self, interaction, user, channel, title, description, kind, filepath):
        """Process event categorization with proper messaging."""
        # Send initial notification to user
        allow_roles_mentions = self.ticket_notify_allowRole(interaction, "CUSTOMER")
        msg = await channel.send(f"{allow_roles_mentions} {user.mention} 專屬對話頻道已創建")
        await msg.delete()

        today = time.strftime('%Y/%m/%d %H:%M')
        
        # Send notification to user via ephemeral message
        notification_embed = discord.Embed(
            title="🎉 專屬對話已建立",
            description=f"**{user.display_name}** 您好！\n\n您的專屬對話頻道 <#{channel.id}> 已成功建立。\n我們的團隊成員將儘快回應您的需求，感謝您的耐心等候。",
            color=0x6366F1
        )
        notification_embed.set_footer(text=today + " ● HackIt Team")
        
        print(f"[HackIt Ticket] User {user} created ticket successfully, created at {today}, ticket channel ID: {channel.id}")
        await interaction.followup.send(embed=notification_embed, ephemeral=True)
        
        # Send event analysis in progress prompt
        loading_embed = discord.Embed(
            title="⏳ 正在分析相關活動...",
            description="我們正在分析您的問題以確定相關的 HackIt 活動，這將需要幾秒鐘的時間。",
            color=0x9CA3AF
        )
        loading_embed.set_footer(text=today + " ● HackIt Team")
        
        loading_message = await channel.send(embed=loading_embed)
        
        # Perform event analysis and categorization
        event_id, event_name = await self.analyze_event(self.get_user_input_from_filepath(filepath))
        
        # Record event categorization result
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(f"* {time.strftime('%Y/%m/%d %H:%M:%S:')} - Event Categorized as {event_name}\n")
        
        # Update channel for event
        await self.update_channel_for_event(channel, interaction.guild, event_id)
        
        # Get user's initial question
        user_initial_input = self.get_user_input_from_filepath(filepath)
        
        # Create final ticket embed with complete information
        ticket_title, ticket_description, _ = self.generate_ticket_info(kind)
        
        final_embed = discord.Embed(
            title=ticket_title,
            description=ticket_description,
            color=0x6366F1
        )
        
        # Add user's initial question if available
        if user_initial_input:
            final_embed.add_field(
                name="📝 您的問題",
                value=f"「{user_initial_input}」",
                inline=False
            )
            final_embed.add_field(
                name="💬 後續說明",
                value="請在此頻道中進一步詳細描述您的需求，我們會盡快回覆！",
                inline=False
            )
        
        # Add AI categorization result
        final_embed.add_field(
            name="🤖 智能分類結果",
            value=f"已自動分類為「**{kind}**」→「**{event_name}**」",
            inline=False
        )
        
        final_embed.set_footer(text=today + " ● HackIt Team")
        
        # Use event-specific view with reselect activity button
        final_view = EventTicketView(user.id)
        
        # Replace the loading message with final result
        try:
            await loading_message.edit(embed=final_embed, view=final_view)
        except Exception as e:
            logger.error(f"Failed to edit loading message, sending new one: {e}")
            # If editing fails, delete old and send new
            try:
                await loading_message.delete()
            except:
                pass
            await channel.send(embed=final_embed, view=final_view)
        
        # Record completion
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(f"* {time.strftime('%Y/%m/%d %H:%M:%S:')} - AI Event Categorization Completed\n")
    
    def get_user_input_from_filepath(self, filepath: str) -> str:
        """Extract user input from file."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in lines:
                    if "UserInput: " in line:
                        return line.replace("UserInput: ", "").strip()
        except Exception as e:
            logger.error(f"Error reading user input from file: {e}")
        return ""
    

    
    async def analyze_user_message(self, user: discord.User) -> tuple:
        """Analyze user message for categorization."""
        try:
            # Read user input from file
            filepath = f'{USER_DATA_PATH}{str(user.id)}.txt'
            user_input = self.get_user_input_from_filepath(filepath)
            
            # Check for photography/media recruitment keywords first
            query = user_input.lower()
            if any(keyword in query for keyword in ['攝影', '影像', '相機', '錄影', '拍攝', '攝像']) and ('招募' in query or '徵' in query or '加入' in query):
                print(f"[HackIt Ticket] 偵測到與攝影/影像相關的招募詞，自動分類為活動諮詢")
                return "活動諮詢", "photography_recruitment_rule", None

            system_prompt = """You are now the HackIt ticket classification specialist. HackIt is an organization where teens organize hackathons for teens, similar to Hack Club.
Please categorize the user's input into one of the following categories:
"活動諮詢": User inquiring about current or past HackIt events, including registration questions.
"提案活動": User proposing new activity ideas or visions to HackIt, seeking assistance to implement them.
"加入我們": User asking how to join the HackIt team or become a volunteer.
"資源需求": User seeking technical support, educational resources, venue or other resource assistance.
"贊助合作": Business or organization wanting to sponsor or collaborate with HackIt.
"反饋投訴": User providing feedback or complaints about HackIt activities or services.
If it doesn't belong to any of these, please answer "其他問題" (Other problem).
The user cannot see your answer; your response is only used for system classification, so focus on outputting only the category name, such as "活動諮詢", "提案活動", etc. Note: Your response should not contain any text other than the category."""
            
            try:
                # Use HacksterBot's unified AI service
                if self._classifier_agent:
                    print(f"[DEBUG] Sending to AI classifier: '{user_input}'")
                    
                    # Pass user input directly to the classifier agent
                    result = await self._classifier_agent.run(user_input)
                    
                    # Extract response text
                    if hasattr(result, 'data'):
                        text = result.data
                    elif hasattr(result, 'response'):
                        text = result.response
                    else:
                        text = str(result)
                    
                    text = text.strip()
                    provider = "unified_ai_service"
                    
                    print(f"[DEBUG] AI classifier raw response: '{text}'")
                else:
                    raise Exception("AI classifier not available")
                
                # Standardize classification result, remove extra spaces and punctuation
                text = text.strip()
                
                # Standardize to system supported classification names
                category_mapping = {
                    "活動諮詢": "活動諮詢",
                    "活動咨詢": "活動諮詢",
                    "提案活動": "提案活動",
                    "加入我們": "加入我們",
                    "資源需求": "資源需求",
                    "資源需要": "資源需求",
                    "贊助合作": "贊助合作",
                    "贊助": "贊助合作",
                    "合作": "贊助合作",
                    "贊助/合作": "贊助合作",
                    "反饋投訴": "反饋投訴",
                    "反饋": "反饋投訴",
                    "投訴": "反饋投訴",
                    "反饋/投訴": "反饋投訴",
                }
                
                # Use mapping table to standardize classification, if not found, keep original
                standardized_category = category_mapping.get(text, text)
                
                # If still not valid classification, classify as "Other Problem"
                valid_categories = ["活動諮詢", "提案活動", "加入我們", "資源需求", "贊助合作", "反饋投訴", "其他問題"]
                if standardized_category not in valid_categories:
                    standardized_category = "其他問題"
                
                print(f"[HackIt Ticket] User {user} ticket classification successful, using {provider}, returned: {text}, standardized to: {standardized_category}")
                return standardized_category, provider, None
            except Exception as e:
                print(f"[HackIt Ticket] User {user} ticket attempt classification failed, API error: {e}")
                
                # Local keyword classification as backup
                query = user_input.lower()
                # Check again for photography/media recruitment keywords
                if any(keyword in query for keyword in ['攝影', '影像', '相機', '錄影', '拍攝', '攝像']) and ('招募' in query or '徵' in query or '加入' in query):
                    return "活動諮詢", "photography_recruitment_rule_fallback", None
                elif any(keyword in query for keyword in ['活動', '報名', '黑客松', '聯絡', '參加']):
                    return "活動諮詢", "local_fallback", None
                elif any(keyword in query for keyword in ['提案', '想法', '建議', '辦活動']):
                    return "提案活動", "local_fallback", None
                elif any(keyword in query for keyword in ['加入', '志工', '志願者', '團隊成員']):
                    return "加入我們", "local_fallback", None
                elif any(keyword in query for keyword in ['資源', '場地', '設備', '教學']):
                    return "資源需求", "local_fallback", None
                elif any(keyword in query for keyword in ['贊助', '合作', '企業', '支持', '錢', '前']):
                    return "贊助合作", "local_fallback", None
                elif any(keyword in query for keyword in ['反饋', '投訴', '問題', '改進']):
                    return "反饋投訴", "local_fallback", None
                else:
                    return "其他問題", "local_fallback", None
        except Exception as e:
            print(f"[HackIt Ticket] User {user} ticket attempt classification failed, system error")
            await asyncio.sleep(3)
            return "Error", "none", e
    
    async def analyze_event(self, query):
        """Analyze query, find the most relevant event."""
        try:
            # Check for photography/media recruitment keywords
            query_lower = query.lower()
            if any(keyword in query_lower for keyword in ['攝影', '影像', '相機', '錄影', '拍攝', '攝像']) and ('招募' in query_lower or '徵' in query_lower or '加入' in query_lower):
                print(f"[HackIt Ticket] 偵測到與攝影/影像相關的招募詞，直接分類到「第五屆中學生黑客松子賽事」")
                # Find 5th HSH event
                events = self.events_config["events"]
                for event in events:
                    if event["id"] == "5th_hsh_special_issues":
                        return event["id"], event["name"]

            # Get active event list
            active_events = [event for event in self.events_config["events"] if event.get("active", True)]
            
            if not active_events:
                return "no_event", "未分類活動"
            
            # Build prompt, let AI determine which HackIt event the query is most related to
            events_prompt = "\n".join([f"{i+1}. {event['name']}: {event['description']}" 
                                     for i, event in enumerate(active_events)])
            
            system_prompt = f"""You are HackIt's event classification assistant. Based on the user's question, determine which HackIt event they are most likely inquiring about.
Here is the current list of events:
{events_prompt}

Please only answer with the number of the most relevant event (1, 2, 3...). If you can't determine, please answer 0. Do not include any other text or explanation."""

            try:
                # Use HacksterBot's unified AI service
                if self._general_agent:
                    full_prompt = f"{system_prompt}\n\nUser query: {query}"
                    
                    result_obj = await self._general_agent.run(full_prompt)
                    
                    # Extract response text
                    if hasattr(result_obj, 'data'):
                        result = result_obj.data
                    elif hasattr(result_obj, 'response'):
                        result = result_obj.response
                    else:
                        result = str(result_obj)
                    
                    provider = "unified_ai_service"
                else:
                    raise Exception("AI general agent not available")
            except Exception as e:
                print(f"Event analysis AI error: {e}")
                # Fallback to keyword matching
                for event in active_events:
                    for keyword in event["keywords"]:
                        if keyword.lower() in query.lower():
                            return event["id"], event["name"]
                return active_events[0]["id"], active_events[0]["name"]
            
            # Process AI response
            result = result.strip()
            
            # Extract digits
            match = re.search(r'^\d+$', result)
            if match:
                event_index = int(result) - 1
                if 0 <= event_index < len(active_events):
                    selected_event = active_events[event_index]
                    return selected_event["id"], selected_event["name"]
            
            # If unable to determine or error, use keyword matching
            for event in active_events:
                for keyword in event["keywords"]:
                    if keyword.lower() in query.lower():
                        return event["id"], event["name"]
            
            # If none match, return default first event
            return active_events[0]["id"], active_events[0]["name"]
            
        except Exception as e:
            print(f"Event analysis error: {e}")
            return "no_event", "未分類活動"
    
    async def clear_event_permissions(self, channel, guild):
        """Clear all event-specific role permissions from channel."""
        try:
            overwrites = channel.overwrites.copy()
            permissions_cleared = False
            
            # Remove permissions for all event roles
            for event in self.events_config["events"]:
                role_id = event.get("role_id")
                if role_id:
                    role = discord.utils.get(guild.roles, id=int(role_id))
                    if role and role in overwrites:
                        del overwrites[role]
                        permissions_cleared = True
                        print(f"Cleared permissions for event role: {event['name']}")
            
            # Apply updated permissions if any changes were made
            if permissions_cleared:
                await channel.edit(overwrites=overwrites)
                print("Successfully cleared all event role permissions")
                
        except Exception as e:
            print(f"Error clearing event permissions: {e}")
    
    async def update_channel_for_event(self, channel, guild, event_id):
        """Update channel permissions based on event ID."""
        try:
            # Find corresponding event
            event = next((e for e in self.events_config["events"] if e["id"] == event_id), None)
            
            if not event:
                return
            
            # Get event corresponding role
            role_id = event.get("role_id")
            if not role_id:
                print(f"Event {event_id} does not have a role ID specified")
                return
                
            role = discord.utils.get(guild.roles, id=int(role_id))
            if not role:
                print(f"Role ID not found: {role_id}")
                return
                
            # Update channel permissions, remove old event roles and add new one
            try:
                overwrites = channel.overwrites.copy()
                
                # Remove permissions for all other event roles to avoid conflicts
                for other_event in self.events_config["events"]:
                    other_role_id = other_event.get("role_id")
                    if other_role_id and other_role_id != role_id:
                        other_role = discord.utils.get(guild.roles, id=int(other_role_id))
                        if other_role and other_role in overwrites:
                            # Remove the old event role permissions
                            del overwrites[other_role]
                            print(f"Removed permissions for previous event role: {other_event['name']}")
                
                # Add permissions for the new event role
                overwrites[role] = discord.PermissionOverwrite(
                    read_messages=True, 
                    send_messages=True,
                    read_message_history=True
                )
                
                # Apply updated permissions
                await channel.edit(overwrites=overwrites)
                print(f"Successfully updated channel permissions for event: {event['name']}")
            except discord.errors.HTTPException as e:
                if e.status == 429:  # Rate limit error
                    wait_time = e.retry_after
                    error_msg = f"操作過於頻繁，受到 Discord 官方限制，請 {int(wait_time/60)+1} 分鐘後再嘗試。"
                    print(f"Rate limited when updating channel. Retry after {wait_time} seconds")
                    
                    # Send user-friendly error message
                    try:
                        await channel.send(f"⚠️ **Discord 速率限制錯誤**\n\n{error_msg}")
                    except:
                        pass
                else:
                    print(f"Error updating channel settings: {e}")
            
        except Exception as e:
            print(f"Error updating channel permissions: {e}")
            # Error won't prevent ticket creation
    
    def generate_ticket_info(self, kind: str):
        """Generate ticket information based on category."""
        allowRole = "CUSTOMER"
        match kind:
            case "活動諮詢":
                title = "活動諮詢"
                description = "您好，感謝您聯繫 HackIt！\n\n您的問題已初步識別為「活動諮詢」。請直接在這個頻道中詳細描述您的需求或疑問，專責團隊成員會儘快回覆。\n\n若您有關於特定活動的問題，歡迎一併說明，這將幫助我們更有效地為您提供協助。"
            case "提案活動":
                allowRole = "DEVELOPER"
                title = "提案活動"
                description = "您好，感謝您向 HackIt 提出活動提案！\n\n我們很重視每位夥伴的創新構想。請在此頻道中分享您的提案概要，專責團隊成員會與您進一步交流並評估可行性。\n\n期待您的想法為青少年科技教育帶來新的可能性。"
            case "加入我們":
                allowRole = "BOTH"
                title = "加入 HackIt"
                description = "您好，感謝您有興趣加入 HackIt 團隊！\n\n請在此頻道中分享您希望參與的方向（如活動籌劃、技術開發、行銷推廣等）以及您的相關經驗，我們會安排適當的面談或交流。"
            case "資源需求":
                title = "資源需求"
                description = "您好，感謝您向 HackIt 提出資源需求！\n\n請在此頻道中說明您所需的資源類型及用途，團隊成員會評估如何最適切地支援您的需求。\n\nHackIt 致力於為青少年創新專案提供必要的資源支持。"
            case "贊助合作":
                allowRole = "DEVELOPER"
                title = "贊助合作"
                description = "您好，感謝您考慮與 HackIt 展開合作！\n\n請在此頻道中分享您的合作構想及期望，我們的專責團隊將與您深入討論合作細節。"
            case "反饋投訴":
                title = "反饋與建議"
                description = "您好，感謝您提供寶貴的反饋！\n\n請在此頻道中分享您的意見或建議，我們會認真考量您的反饋，並與您討論可能的改進方向。"
            case _:
                title = "一般諮詢"
                description = "您好，感謝您聯繫 HackIt！\n請在此頻道中詳細說明您的需求或問題，團隊成員會儘快回覆並提供協助。\nHackIt 致力於支持青少年的科技與創新探索，期待能為您提供適切的協助。"

        return title, description, allowRole
    
    def get_channel_overwrites(self, guild: discord.Guild, user: discord.User, allow_role: str) -> dict:
        """Get channel permission overwrites."""
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True),
            user: discord.PermissionOverwrite(read_messages=True, attach_files=True, embed_links=True,
                                             read_message_history=True)
        }
        
        # Add role permissions based on ticket type
        role_id = None
        if allow_role == "CUSTOMER":
            role_id = self.ticket_customer_id
        elif allow_role == "DEVELOPER":
            role_id = self.ticket_developer_id
        elif allow_role == "ADMIN":
            role_id = self.ticket_admin_id
        
        if role_id:
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    read_message_history=True
                )
        
        return overwrites
    
    def ticket_notify_allowRole(self, interaction: discord.Interaction, allow_role: str):
        """Get role mentions for notifications."""
        guild = interaction.guild
        allow_roles = []
        
        # Get roles
        customer_role = discord.utils.get(guild.roles, id=self.ticket_customer_id)
        developer_role = discord.utils.get(guild.roles, id=self.ticket_developer_id)
        admin_role = discord.utils.get(guild.roles, id=self.ticket_admin_id)
        
        # Add to notification list based on role type
        match allow_role:
            case "CUSTOMER":
                if customer_role:
                    allow_roles.append(customer_role)
            case "DEVELOPER":
                if developer_role:
                    allow_roles.append(developer_role)
            case "BOTH":
                if customer_role:
                    allow_roles.append(customer_role)
                if developer_role:
                    allow_roles.append(developer_role)
            case _:
                if admin_role:
                    allow_roles.append(admin_role)
        
        # If no roles found, default to not adding any role mentions
        return " ".join(role.mention for role in allow_roles) if allow_roles else ""
    
    async def finalize_ticket_creation(self, interaction, user, channel, allowRole, title, description, apply, kind):
        """Finalize ticket creation."""
        allow_roles_mentions = self.ticket_notify_allowRole(interaction, allowRole)
        msg = await channel.send(f"{allow_roles_mentions} {user.mention} 專屬對話頻道已創建")
        await msg.delete()

        today = time.strftime('%Y/%m/%d %H:%M')
        
        # Send notification to user via ephemeral message
        notification_embed = discord.Embed(
            title="🎉 專屬對話已建立",
            description=f"**{user.display_name}** 您好！\n\n您的專屬對話頻道 <#{channel.id}> 已成功建立。\n我們的團隊成員將儘快回應您的需求，感謝您的耐心等候。",
            color=0x6366F1
        )
        notification_embed.set_footer(text=today + " ● HackIt Team")
        
        print(f"[HackIt Ticket] User {user} created ticket successfully, created at {today}, ticket channel ID: {channel.id}")
        await interaction.followup.send(embed=notification_embed, ephemeral=True)

        # Send categorization message with user's initial question
        filepath = f'{USER_DATA_PATH}{str(user.id)}.txt'
        user_initial_input = self.get_user_input_from_filepath(filepath)
        
        category_embed = discord.Embed(
            title=title,
            description=description,
            color=0x6366F1
        )
        
        # Add user's initial question if available
        if user_initial_input:
            category_embed.add_field(
                name="📝 您的問題",
                value=f"「{user_initial_input}」",
                inline=False
            )
            category_embed.add_field(
                name="💬 後續說明",
                value="請在此頻道中進一步詳細描述您的需求，我們會盡快回覆！",
                inline=False
            )
        
        category_embed.set_footer(text=today + " ● HackIt Team")
        
        # Add management view
        view = GenerateTicketView(apply)
        await channel.send(embed=category_embed, view=view)
        
        # Record ticket creation completed process
        with open(filepath, "a", encoding="utf-8") as f:
            f.write("* " + time.strftime('%Y/%m/%d %H:%M:%S:') + " - " + "Ticket Setup Completed\n")
    
    async def check_ticket_channel_exists(self, guild, filepath):
        """Check if ticket channel actually exists."""
        channel_id = None
        
        try:
            # Read channel ID from user ticket file
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in lines:
                    if "Ticket Channel Created:" in line:
                        # Extract channel ID
                        channel_id_match = line.strip().split("Ticket Channel Created:")[1].strip()
                        if channel_id_match:
                            channel_id = int(channel_id_match)
                            break
            
            # If channel ID found, check if it actually exists
            if channel_id:
                channel = guild.get_channel(channel_id)
                if channel:
                    # Channel exists
                    return channel_id
                else:
                    # Channel doesn't exist
                    print(f"[HackIt Ticket] Channel ID {channel_id} doesn't exist, possibly deleted")
                    return None
            else:
                # File doesn't contain channel ID
                print(f"[HackIt Ticket] User ticket file doesn't contain channel ID")
                return None
                
        except Exception as e:
            print(f"[HackIt Ticket] Error checking channel existence: {e}")
            return None
    
    async def close_channel(self, channel, guild, user):
        """Close a channel and handle cleanup."""
        # Create transcript
        transcript_file, log_file = await self.create_transcript(channel, guild, user)
        
        filepath = f'{USER_DATA_PATH}{user.id}.txt'
        send_success = False
        
        # Send files to user
        if user:
            try:
                if transcript_file:
                    await user.send(content=f"您的工單 {channel.name} 已被關閉，以下是您的對話紀錄。若有任何需求歡迎再次與我們聯絡。", file=transcript_file)
                else:
                    await user.send(content=f"您的工單 {channel.name} 已被關閉，若有任何需求歡迎再次與我們聯絡。")
                
                send_success = True
            except discord.Forbidden:
                logger.warning(f"Unable to send transcript to user {user.id}, DM may be closed")
            except Exception as e:
                logger.error(f"Error sending transcript to user: {e}")
        
        # Clean up file
        if os.path.exists(filepath):
            if send_success:
                os.remove(filepath)
                logger.info(f"User record file {filepath} deleted after successful DM")
            else:
                logger.warning(f"Keeping user record file {filepath} due to DM failure")
        
        # Ticket cleanup completed (no database operation needed as we use file-based tracking)
        
        # Delete channel
        await channel.delete()
        logger.info(f"Ticket {channel.name} has been closed")
    
    async def create_transcript(self, channel, guild, user):
        """Create transcript of the channel."""
        transcript_file = None
        log_file = None
        
        try:
            # Export chat history
            transcript = await chat_exporter.export(channel)
            if transcript:
                try:
                    transcript_bytes = transcript.encode()
                    transcript_file = discord.File(io.BytesIO(transcript_bytes), filename=f"{channel.name}.html")
                    logger.info(f"Successfully created chat transcript for {channel.name}")
                except Exception as e:
                    logger.error(f"Error converting transcript to file: {e}")
            
            # Prepare ticket log
            ticket_log_path = f"{USER_DATA_PATH}{user.id}.txt"
            if os.path.exists(ticket_log_path):
                try:
                    with open(ticket_log_path, 'rb') as original_file:
                        file_content = original_file.read()
                    log_file = discord.File(io.BytesIO(file_content), filename=f"ticket_log_{user.id}.txt")
                    logger.info(f"Successfully created log file from {ticket_log_path}")
                except Exception as e:
                    logger.error(f"Error creating log file: {e}")
        
        except Exception as e:
            logger.error(f"Error creating transcript: {e}")
        
        # Send to log channel if configured
        if self.ticket_log_channel_id > 0:
            log_channel = guild.get_channel(self.ticket_log_channel_id)
            if log_channel:
                try:
                    if transcript_file:
                        await log_channel.send(content=f"此檔案為 {channel.name} 的對話紀錄", file=transcript_file)
                        if transcript:
                            transcript_file = discord.File(io.BytesIO(transcript.encode()), filename=f"{channel.name}.html")
                    
                    if log_file:
                        await log_channel.send(content=f"此檔案為 {channel.name} 的工單紀錄", file=log_file)
                        ticket_log_path = f"{USER_DATA_PATH}{user.id}.txt"
                        if os.path.exists(ticket_log_path):
                            with open(ticket_log_path, 'rb') as original_file:
                                file_content = original_file.read()
                            log_file = discord.File(io.BytesIO(file_content), filename=f"ticket_log_{user.id}.txt")
                except Exception as e:
                    logger.error(f"Error sending logs to log channel: {e}")
        
        return transcript_file, log_file
    
    @discord.app_commands.command(name="create_ticket_panel", description="創建工單面板（僅限管理員）")
    async def create_ticket_panel(self, interaction: discord.Interaction):
        """Create ticket panel."""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ 只有管理員可以創建工單面板", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        today = time.strftime('%Y/%m/%d %H:%M')
        
        embed = discord.Embed(
            title="✨ HackIt 聯絡中心 | Contact Hub",
            description="### 👋 嗨！需要協助或有任何想法嗎？\n\n無論您想了解我們的活動、提出合作提案、加入團隊、尋求資源協助，或是有任何疑問想諮詢，我們都非常樂意聆聽與交流！\n\n**📝 與我們聯繫的方式：**\n• 點擊下方「✉️ 聯絡 HackIt」按鈕\n• 簡單描述您的需求或問題\n• 系統會為您創建專屬對話頻道\n• 在專屬頻道中與我們的團隊成員即時交流\n\n我們的團隊將以最快速度回應您的訊息！",
            colour=0x6366F1
        )
        
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1006209980417982545/1371905827937583114/hackit_logo_inkscape_1.png?ex=6824d65e&is=682384de&hm=2bcdfa91f5c3b5ea1aa37cfe131c3154a9357e36a173a5ffdefe3f975a5a388a&")
        embed.set_footer(text=f"{today} • HackIt Team")
        
        await interaction.followup.send(embed=embed, view=GenerateTicket())
    
    @discord.app_commands.command(name="close_ticket", description="關閉當前工單")
    async def close_ticket_cmd(self, interaction: discord.Interaction):
        """Close current ticket command."""
        topic = interaction.channel.topic
        if not topic or not topic.isdigit():
            await interaction.response.send_message("❌ 此頻道不是工單頻道", ephemeral=True)
            return
        
        user_id = int(topic)
        user = interaction.guild.get_member(user_id)
        
        if not user:
            await interaction.response.send_message("❌ 找不到工單創建者", ephemeral=True)
            return
        
        # Check permissions
        is_staff = any(role.name in ["Admin", "Moderator", "Staff"] for role in interaction.user.roles)
        if interaction.user.id != user_id and not is_staff:
            await interaction.response.send_message("❌ 只有工單創建者或工作人員可以關閉工單", ephemeral=True)
            return
        
        await interaction.response.send_message("正在處理...")
        await self.close_channel(interaction.channel, interaction.guild, user)


def setup(bot, config):
    """Set up the tickets module."""
    return TicketsModule(bot, config) 
