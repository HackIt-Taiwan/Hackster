"""
Blackjack game logic implementation.
"""
import random
from enum import Enum
from typing import List, Optional, Tuple
from dataclasses import dataclass


class Suit(Enum):
    """Card suits."""
    HEARTS = "♥️"
    DIAMONDS = "♦️"
    CLUBS = "♣️"
    SPADES = "♠️"


class Rank(Enum):
    """Card ranks with their values."""
    ACE = ("A", 11)
    TWO = ("2", 2)
    THREE = ("3", 3)
    FOUR = ("4", 4)
    FIVE = ("5", 5)
    SIX = ("6", 6)
    SEVEN = ("7", 7)
    EIGHT = ("8", 8)
    NINE = ("9", 9)
    TEN = ("10", 10)
    JACK = ("J", 10)
    QUEEN = ("Q", 10)
    KING = ("K", 10)
    
    def __init__(self, display, card_value):
        self.display = display
        self.card_value = card_value


@dataclass
class Card:
    """A playing card."""
    suit: Suit
    rank: Rank
    
    def __str__(self) -> str:
        return f"{self.rank.display}{self.suit.value}"


class Hand:
    """A hand of cards in blackjack."""
    
    def __init__(self):
        self.cards: List[Card] = []
    
    def add_card(self, card: Card) -> None:
        """Add a card to the hand."""
        self.cards.append(card)
    
    def get_value(self) -> int:
        """Calculate the value of the hand."""
        total = 0
        aces = 0
        
        for card in self.cards:
            if card.rank == Rank.ACE:
                aces += 1
            total += card.rank.card_value
        
        # Adjust for aces (count as 1 instead of 11 if needed)
        while total > 21 and aces > 0:
            total -= 10
            aces -= 1
        
        return total
    
    def is_blackjack(self) -> bool:
        """Check if the hand is a blackjack (21 with 2 cards)."""
        return len(self.cards) == 2 and self.get_value() == 21
    
    def is_bust(self) -> bool:
        """Check if the hand is bust (over 21)."""
        return self.get_value() > 21
    
    def is_soft(self) -> bool:
        """Check if the hand contains an ace counted as 11."""
        total = sum(card.rank.card_value for card in self.cards)
        return total != self.get_value()
    
    def display(self, hide_first: bool = False) -> str:
        """Display the hand as a string."""
        if hide_first and len(self.cards) > 0:
            cards_str = f"🂠 {' '.join(str(card) for card in self.cards[1:])}"
            visible_value = sum(card.rank.card_value for card in self.cards[1:])
            # Adjust for aces in visible cards
            aces = sum(1 for card in self.cards[1:] if card.rank == Rank.ACE)
            while visible_value > 21 and aces > 0:
                visible_value -= 10
                aces -= 1
            return f"{cards_str} (顯示: {visible_value})"
        else:
            cards_str = " ".join(str(card) for card in self.cards)
            value = self.get_value()
            soft_indicator = " (軟)" if self.is_soft() else ""
            return f"{cards_str} (總計: {value}{soft_indicator})"


class Deck:
    """A deck of playing cards."""
    
    def __init__(self, num_decks: int = 1):
        """Initialize a deck with the specified number of standard decks."""
        self.cards: List[Card] = []
        self.num_decks = num_decks
        self.reset()
    
    def reset(self) -> None:
        """Reset the deck with all cards."""
        self.cards = []
        for _ in range(self.num_decks):
            for suit in Suit:
                for rank in Rank:
                    self.cards.append(Card(suit, rank))
        self.shuffle()
    
    def shuffle(self) -> None:
        """Shuffle the deck."""
        random.shuffle(self.cards)
    
    def deal_card(self) -> Optional[Card]:
        """Deal a card from the deck."""
        if len(self.cards) == 0:
            return None
        return self.cards.pop()
    
    def cards_remaining(self) -> int:
        """Get the number of cards remaining in the deck."""
        return len(self.cards)


class GameState(Enum):
    """Game states."""
    WAITING_FOR_PLAYER = "waiting_for_player"
    DEALER_TURN = "dealer_turn"
    GAME_OVER = "game_over"


class GameResult(Enum):
    """Game results."""
    PLAYER_WIN = "player_win"
    DEALER_WIN = "dealer_win"
    TIE = "tie"
    PLAYER_BLACKJACK = "player_blackjack"
    DEALER_BLACKJACK = "dealer_blackjack"
    PLAYER_BUST = "player_bust"
    DEALER_BUST = "dealer_bust"


class BlackjackGame:
    """A blackjack game instance."""
    
    def __init__(self, player_id: int, num_decks: int = 1):
        """
        Initialize a new blackjack game.
        
        Args:
            player_id: Discord user ID of the player
            num_decks: Number of decks to use
        """
        self.player_id = player_id
        self.deck = Deck(num_decks)
        self.player_hand = Hand()
        self.dealer_hand = Hand()
        self.state = GameState.WAITING_FOR_PLAYER
        self.result: Optional[GameResult] = None
        
        # Deal initial cards
        self._deal_initial_cards()
    
    def _deal_initial_cards(self) -> None:
        """Deal the initial two cards to player and dealer."""
        # Deal two cards to player
        self.player_hand.add_card(self.deck.deal_card())
        self.player_hand.add_card(self.deck.deal_card())
        
        # Deal two cards to dealer (one face up, one face down)
        self.dealer_hand.add_card(self.deck.deal_card())
        self.dealer_hand.add_card(self.deck.deal_card())
        
        # Check for blackjacks
        if self.player_hand.is_blackjack() or self.dealer_hand.is_blackjack():
            self._determine_winner()
    
    def hit(self) -> bool:
        """
        Player hits (takes another card).
        
        Returns:
            True if the action was successful, False otherwise
        """
        if self.state != GameState.WAITING_FOR_PLAYER:
            return False
        
        self.player_hand.add_card(self.deck.deal_card())
        
        if self.player_hand.is_bust():
            self.result = GameResult.PLAYER_BUST
            self.state = GameState.GAME_OVER
        
        return True
    
    def stand(self) -> bool:
        """
        Player stands (keeps current hand).
        
        Returns:
            True if the action was successful, False otherwise
        """
        if self.state != GameState.WAITING_FOR_PLAYER:
            return False
        
        self.state = GameState.DEALER_TURN
        self._dealer_play()
        return True
    
    def _dealer_play(self) -> None:
        """Execute dealer's turn according to standard rules."""
        # Dealer hits on 16 and stands on 17
        while self.dealer_hand.get_value() < 17:
            self.dealer_hand.add_card(self.deck.deal_card())
        
        self._determine_winner()
    
    def _determine_winner(self) -> None:
        """Determine the winner of the game."""
        self.state = GameState.GAME_OVER
        
        player_value = self.player_hand.get_value()
        dealer_value = self.dealer_hand.get_value()
        player_blackjack = self.player_hand.is_blackjack()
        dealer_blackjack = self.dealer_hand.is_blackjack()
        
        # Check for blackjacks first
        if player_blackjack and dealer_blackjack:
            self.result = GameResult.TIE
        elif player_blackjack:
            self.result = GameResult.PLAYER_BLACKJACK
        elif dealer_blackjack:
            self.result = GameResult.DEALER_BLACKJACK
        # Check for busts
        elif self.player_hand.is_bust():
            self.result = GameResult.PLAYER_BUST
        elif self.dealer_hand.is_bust():
            self.result = GameResult.DEALER_BUST
        # Compare values
        elif player_value > dealer_value:
            self.result = GameResult.PLAYER_WIN
        elif dealer_value > player_value:
            self.result = GameResult.DEALER_WIN
        else:
            self.result = GameResult.TIE
    
    def can_hit(self) -> bool:
        """Check if player can hit."""
        return self.state == GameState.WAITING_FOR_PLAYER and not self.player_hand.is_bust()
    
    def can_stand(self) -> bool:
        """Check if player can stand."""
        return self.state == GameState.WAITING_FOR_PLAYER
    
    def is_game_over(self) -> bool:
        """Check if the game is over."""
        return self.state == GameState.GAME_OVER
    
    def get_result_message(self) -> str:
        """Get a descriptive message about the game result."""
        if not self.is_game_over():
            return "遊戲進行中..."
        
        result_messages = {
            GameResult.PLAYER_BLACKJACK: "🎉 恭喜！你獲得了21點黑傑克！",
            GameResult.DEALER_BLACKJACK: "😞 莊家獲得了21點黑傑克，你輸了",
            GameResult.PLAYER_WIN: "🎉 恭喜！你贏了！",
            GameResult.DEALER_WIN: "😞 莊家贏了，再試一次吧！",
            GameResult.TIE: "🤝 平手！",
            GameResult.PLAYER_BUST: "💥 你爆牌了！超過21點",
            GameResult.DEALER_BUST: "🎉 莊家爆牌了！你贏了！"
        }
        
        return result_messages.get(self.result, "未知結果")
    
    def get_game_display(self) -> str:
        """Get a formatted display of the current game state."""
        lines = []
        lines.append("🃏 **21點遊戲** 🃏")
        lines.append("")
        
        # Dealer's hand
        if self.state == GameState.WAITING_FOR_PLAYER:
            lines.append(f"🤖 **莊家 (AI):** {self.dealer_hand.display(hide_first=True)}")
        else:
            lines.append(f"🤖 **莊家 (AI):** {self.dealer_hand.display()}")
        
        lines.append("")
        
        # Player's hand
        lines.append(f"👤 **你:** {self.player_hand.display()}")
        
        if self.is_game_over():
            lines.append("")
            lines.append(self.get_result_message())
        
        return "\n".join(lines) 