"""
AI opponent service for blackjack games.
Provides intelligent commentary and strategic analysis.
"""
import logging
from typing import Optional, TYPE_CHECKING
import random

from modules.ai.services.ai_select import get_agent, create_general_agent

if TYPE_CHECKING:
    from core.bot import HacksterBot
    from core.config import Config
    from ..game import BlackjackGame

logger = logging.getLogger(__name__)


class AIOpponent:
    """AI opponent that provides commentary and strategic insights."""
    
    def __init__(self, bot: 'HacksterBot', config: 'Config'):
        """
        Initialize the AI opponent.
        
        Args:
            bot: Bot instance
            config: Configuration object
        """
        self.bot = bot
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.ai_agent = None
        
        # Commentary templates for fallback
        self.start_comments = [
            "好運氣！讓我們開始這場精彩的21點對決吧！",
            "我已經準備好了，你準備接受挑戰了嗎？",
            "新的一局開始了！記住，21點是技巧與運氣的結合。",
            "歡迎來到21點桌！我期待與你的對戰。",
            "讓我們看看誰的策略更勝一籌！"
        ]
        
        self.hit_comments = [
            "大膽的選擇！讓我們看看你的運氣如何。",
            "要牌是明智的決定，繼續保持！",
            "有趣的策略，我很好奇你的下一步。",
            "勇敢的玩家！風險與回報並存。",
            "好的決定！讓我們看看結果如何。"
        ]
        
        self.stand_comments = [
            "保守的策略，有時候知道何時停下是最重要的。",
            "穩健的選擇！讓我們看看我的表現如何。",
            "明智的決定，現在輪到我展示實力了。",
            "停牌是個好選擇，接下來看我的了！",
            "你很了解自己的極限，這很重要。"
        ]
        
        self.win_comments = [
            "恭喜你！這是一場精彩的勝利！",
            "太棒了！你的策略非常成功。",
            "出色的表現！你真的很會玩21點。",
            "優秀的決策！你值得這場勝利。",
            "令人印象深刻的遊戲！再來一局嗎？"
        ]
        
        self.lose_comments = [
            "這次運氣不在你這邊，但你表現得很好！",
            "雖然輸了，但你的策略很不錯。再試一次吧！",
            "21點有時候就是這樣，下次會更好的！",
            "別氣餒！每個高手都經歷過失敗。",
            "這只是暫時的，繼續練習你會變得更強！"
        ]
    
    async def initialize(self) -> None:
        """Initialize the AI opponent."""
        try:
            # Try to get AI agent for commentary
            model = await get_agent(self.config, "auxiliary")
            if model:
                self.ai_agent = await create_general_agent(
                    model=model,
                    system_prompt=self._get_system_prompt()
                )
                self.logger.info("AI opponent initialized with AI agent")
            else:
                self.logger.warning("AI agent not available, using template responses")
                
        except Exception as e:
            self.logger.warning(f"Failed to initialize AI agent, using templates: {e}")
    
    async def close(self) -> None:
        """Close the AI opponent."""
        self.ai_agent = None
        self.logger.info("AI opponent closed")
    
    def _get_system_prompt(self) -> str:
        """Get the system prompt for the AI agent."""
        return """你是一個友好的21點遊戲AI莊家。你的任務是為玩家提供有趣的評論和鼓勵。

特點：
- 保持友好和鼓勵的語調
- 提供簡短但有趣的評論（不超過50字）
- 偶爾給出基本的21點策略提示
- 慶祝玩家的好運和好決策
- 在玩家失敗時給予安慰和鼓勵
- 使用繁體中文回應
- 保持輕鬆愉快的氛圍

請根據遊戲情況提供適當的評論。"""
    
    async def get_game_start_commentary(self, game: 'BlackjackGame') -> Optional[str]:
        """
        Get commentary for game start.
        
        Args:
            game: The blackjack game instance
            
        Returns:
            Commentary string or None
        """
        try:
            if self.ai_agent:
                prompt = f"""遊戲開始！
玩家手牌: {game.player_hand.display()}
我的明牌: {game.dealer_hand.cards[1] if len(game.dealer_hand.cards) > 1 else 'Unknown'}

請給出一個簡短的開場評論（不超過40字）。"""
                
                response = await self.ai_agent.run(prompt)
                if response and hasattr(response, 'data'):
                    return str(response.data).strip()
            
            # Fallback to template
            return random.choice(self.start_comments)
            
        except Exception as e:
            self.logger.error(f"Failed to get game start commentary: {e}")
            return random.choice(self.start_comments)
    
    async def get_action_commentary(self, game: 'BlackjackGame', action: str) -> Optional[str]:
        """
        Get commentary for player actions.
        
        Args:
            game: The blackjack game instance
            action: The action taken ('hit' or 'stand')
            
        Returns:
            Commentary string or None
        """
        try:
            if self.ai_agent:
                prompt = f"""玩家執行了 {action} 動作。
玩家手牌: {game.player_hand.display()}
遊戲狀態: {'進行中' if not game.is_game_over() else '結束'}

請給出一個簡短的評論（不超過35字）。"""
                
                response = await self.ai_agent.run(prompt)
                if response and hasattr(response, 'data'):
                    return str(response.data).strip()
            
            # Fallback to templates
            if action == 'hit':
                return random.choice(self.hit_comments)
            else:
                return random.choice(self.stand_comments)
                
        except Exception as e:
            self.logger.error(f"Failed to get action commentary: {e}")
            if action == 'hit':
                return random.choice(self.hit_comments)
            else:
                return random.choice(self.stand_comments)
    
    async def get_result_commentary(self, game: 'BlackjackGame') -> Optional[str]:
        """
        Get commentary for game results.
        
        Args:
            game: The completed blackjack game instance
            
        Returns:
            Commentary string or None
        """
        try:
            if self.ai_agent and game.is_game_over():
                player_won = game.result.name in ['PLAYER_WIN', 'PLAYER_BLACKJACK', 'DEALER_BUST']
                
                prompt = f"""遊戲結束！
玩家手牌: {game.player_hand.display()}
莊家手牌: {game.dealer_hand.display()}
結果: {game.get_result_message()}
玩家{'勝利' if player_won else '失敗'}

請給出一個{'恭喜' if player_won else '鼓勵'}的評論（不超過40字）。"""
                
                response = await self.ai_agent.run(prompt)
                if response and hasattr(response, 'data'):
                    return str(response.data).strip()
            
            # Fallback to templates
            if game.result.name in ['PLAYER_WIN', 'PLAYER_BLACKJACK', 'DEALER_BUST']:
                return random.choice(self.win_comments)
            else:
                return random.choice(self.lose_comments)
                
        except Exception as e:
            self.logger.error(f"Failed to get result commentary: {e}")
            if game.result.name in ['PLAYER_WIN', 'PLAYER_BLACKJACK', 'DEALER_BUST']:
                return random.choice(self.win_comments)
            else:
                return random.choice(self.lose_comments)
    
    async def get_strategy_tip(self, game: 'BlackjackGame') -> Optional[str]:
        """
        Get a strategic tip based on current game state.
        
        Args:
            game: The blackjack game instance
            
        Returns:
            Strategy tip string or None
        """
        try:
            if not self.ai_agent or game.is_game_over():
                return None
            
            prompt = f"""當前遊戲狀態分析：
玩家手牌: {game.player_hand.display()}
莊家明牌: {game.dealer_hand.cards[1] if len(game.dealer_hand.cards) > 1 else 'Unknown'}

請給出一個簡短的基本策略建議（不超過30字）。"""
            
            response = await self.ai_agent.run(prompt)
            if response and hasattr(response, 'data'):
                tip = str(response.data).strip()
                return f"💡 策略提示：{tip}"
                
        except Exception as e:
            self.logger.error(f"Failed to get strategy tip: {e}")
        
        return None 