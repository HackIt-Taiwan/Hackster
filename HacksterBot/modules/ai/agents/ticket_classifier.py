"""
Ticket classifier agent for HacksterBot.
Classifies user ticket requests into appropriate categories.
"""
import json
import os
from pydantic_ai import Agent


def load_events_config():
    """Load events configuration from JSON file."""
    events_config_path = "data/events.json"
    
    try:
        if os.path.exists(events_config_path):
            with open(events_config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading events configuration: {e}")
    
    return {"events": []}


def generate_system_prompt():
    """Generate system prompt with dynamic events list."""
    events_config = load_events_config()
    
    # Build events list for prompt
    events_list = []
    all_keywords = []
    
    for event in events_config.get("events", []):
        if event.get("active", True) and event["id"] != "do_not_auto_select_this":
            name = event["name"]
            description = event.get("description", "")
            events_list.append(f"- {name}: {description}")
            
            # Collect keywords
            keywords = event.get("keywords", [])
            all_keywords.extend(keywords)
            # Add event name parts as keywords
            name_keywords = name.lower().split()
            all_keywords.extend(name_keywords)
    
    events_text = "\n".join(events_list) if events_list else "- (No active events currently)"
    keywords_text = ", ".join(f'"{kw}"' for kw in set(all_keywords) if kw) if all_keywords else ""
    
    return f"""You are now the HackIt ticket classification specialist. HackIt is an organization where teens organize hackathons for teens, similar to Hack Club.

HackIt current and upcoming events include:
{events_text}

Please categorize the user's input into one of the following categories:
"活動諮詢": User inquiring about current or past HackIt events, including registration questions, event details, or mentioning specific event names.
"提案活動": User proposing new activity ideas or visions to HackIt, seeking assistance to implement them.
"加入我們": User asking how to join the HackIt team or become a volunteer.
"資源需求": User seeking technical support, educational resources, venue or other resource assistance.
"贊助合作": Business or organization wanting to sponsor or collaborate with HackIt.
"反饋投訴": User providing feedback or complaints about HackIt activities or services.
"其他問題": If it doesn't belong to any of these categories.

IMPORTANT: If the user mentions any event names or keywords related to HackIt events (like {keywords_text}, "hackathon", "黑客松", event dates, etc.), classify as "活動諮詢".

The user cannot see your answer; your response is only used for system classification, so focus on outputting only the category name, such as "活動諮詢", "提案活動", etc. Note: Your response should not contain any text other than the category."""


async def create_ticket_classifier_agent(model) -> Agent:
    """
    Create a ticket classifier agent with the specified model.
    
    Args:
        model: AI model instance
        
    Returns:
        Configured Agent instance
    """
    # Set up the agent with classification-specific settings
    if hasattr(model, 'temperature'):
        model.temperature = 0.2  # Low temperature for consistent classification
    if hasattr(model, 'max_tokens'):
        model.max_tokens = 16
    
    # Generate dynamic system prompt from events.json
    system_prompt = generate_system_prompt()
    
    # Create agent with the dynamically generated prompt
    agent = Agent(model, system_prompt=system_prompt)
    return agent 