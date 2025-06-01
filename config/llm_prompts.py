# graphforrag_core/llm_prompts.py
from pydantic import BaseModel, Field
from typing import List, Optional

# --- Pydantic Models for LLM Output ---

class ExtractedEntity(BaseModel):
    """
    Represents a single entity extracted from text.
    """
    name: str = Field(..., description="The clearly identified and most complete/canonical name of the entity as found or inferred from the text. Should be specific and unambiguous (e.g., full names if available).") # MODIFIED description
    label: str = Field(default="GenericEntity", description="A general ontological label for the entity (e.g., Person, Organization, Location, Product, Concept). Start with generic labels.")
    description: Optional[str] = Field(default=None, description="A brief contextual description or summary of the entity based on the source text.")

class ExtractedEntitiesList(BaseModel):
    """
    A list of entities extracted from a piece of text.
    """
    entities: List[ExtractedEntity] = Field(default_factory=list, description="A list of unique entities found in the text.")

# --- Prompt Templates for Entity Extraction ---

ENTITY_EXTRACTION_SYSTEM_PROMPT = """
You are an expert AI assistant tasked with identifying and extracting named entities from the provided text.
Your goal is to identify distinct real-world objects, concepts, persons, organizations, locations, products, etc., and represent them consistently.

Guidelines:
- Focus on extracting nouns or noun phrases that represent distinct entities.
- For each entity, provide the most complete and canonical name possible based on the information in the CURRENT TEXT. For example, if "Mr. John Smith" and "Smith" refer to the same person in the text, use "John Smith". If only "Pooh" is mentioned, use "Pooh", but if "Winnie-the-Pooh" is mentioned, prefer that.
- If an entity is mentioned multiple times in the CURRENT TEXT, extract it only ONCE using its most representative or complete name.
- For the 'label', assign a general category (e.g., Person, Organization, Location, Product, Concept, Event, Artwork, Miscellaneous). Start with broad categories. Consistency in labeling for the same entity across different mentions is important if discernible.
- If possible, provide a brief contextual description for the entity based *only* on the provided CURRENT TEXT. If the entity is mentioned multiple times, synthesize the description.
- Do NOT extract attributes of entities as separate entities (e.g., for "blue car", extract "car" as an entity, not "blue").
- Do NOT extract actions or verbs as entities.
- If the text is short and contains no clear entities, you can return an empty list.
"""

ENTITY_EXTRACTION_USER_PROMPT_TEMPLATE = """
Please extract all distinct entities from the following text content.
If contextual information from previous turns/chunks is provided, use it to help disambiguate or understand the current text, but primarily focus on extracting entities explicitly mentioned or clearly implied in the CURRENT TEXT.

CONTEXT (Optional, from previous text or related documents):
{context_text}

CURRENT TEXT to extract entities from:
{text_content}
"""