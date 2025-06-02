# config/llm_prompts.py
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any # Added Dict

# --- Pydantic Models for LLM Output (Entity Extraction) ---
class ExtractedEntity(BaseModel):
    name: str = Field(..., description="The clearly identified and most complete/canonical name of the entity as found or inferred from the text. Should be specific and unambiguous (e.g., full names if available).")
    label: str = Field(default="GenericEntity", description="A general ontological label for the entity (e.g., Person, Organization, Location, Product, Concept). Start with generic labels.")
    description: Optional[str] = Field(default=None, description="A brief, single-sentence contextual description of the entity based on the source text. Max 20 words.")

class ExtractedEntitiesList(BaseModel):
    entities: List[ExtractedEntity] = Field(default_factory=list, description="A list of unique entities found in the text.")

# --- Pydantic Models for LLM Output (Entity Deduplication) ---
class ExistingEntityCandidate(BaseModel):
    uuid: str
    name: str
    label: str
    description: Optional[str] = None

class EntityDeduplicationDecision(BaseModel):
    is_duplicate: bool = Field(..., description="True if the new entity is considered a duplicate of one of the existing candidates, False otherwise.")
    duplicate_of_uuid: Optional[str] = Field(default=None, description="The UUID of the existing candidate that the new entity is a duplicate of. Null if not a duplicate.")
    canonical_name: str = Field(..., description="The suggested canonical/best name for this entity (either the new entity's name or an existing candidate's name, or a combined/improved version).")
    canonical_description: Optional[str] = Field(default=None, description="A synthesized, concise, and informative description for the entity, incorporating information from the new mention and any existing description if it's a duplicate. Should be based SOLELY on provided descriptions.")

# --- NEW Pydantic Models for LLM Output (Relationship Extraction) ---
class ExtractedRelationship(BaseModel):
    """
    Represents a single directional relationship extracted between two entities.
    """
    source_entity_name: str = Field(..., description="The name of the source entity in the relationship (must exactly match one of the provided entity names).")
    target_entity_name: str = Field(..., description="The name of the target entity in the relationship (must exactly match one of the provided entity names).")
    relation_label: str = Field(..., description="A concise label for the relationship in SCREAMING_SNAKE_CASE (e.g., WORKS_FOR, LOCATED_IN, INTERACTED_WITH, USES_ITEM).")
    fact_sentence: str = Field(..., description="A complete natural language sentence clearly stating the relationship between the source and target entity, derived directly from the text. Max 30 words.")

class ExtractedRelationshipsList(BaseModel):
    """
    A list of relationships extracted from a piece of text involving a given set of entities.
    """
    relationships: List[ExtractedRelationship] = Field(default_factory=list, description="A list of relationships found in the text between the provided entities.")


# --- Prompt Templates for Entity Extraction ---
ENTITY_EXTRACTION_SYSTEM_PROMPT = """
You are an expert AI assistant tasked with identifying and extracting named entities from the provided text.
Your goal is to identify distinct real-world objects, concepts that are treated as subjects/objects, persons, organizations, locations, products, etc., and represent them consistently.

Guidelines:
- Focus on extracting nouns or noun phrases that represent distinct, tangible or clearly defined conceptual entities.
- For each entity, provide the most complete and canonical name possible based on the information in the CURRENT TEXT. For example, if "Mr. John Smith" and "Smith" refer to the same person in the text, use "John Smith". If only "Pooh" is mentioned, use "Pooh", but if "Winnie-the-Pooh" is mentioned, prefer that.
- If an entity is mentioned multiple times in the CURRENT TEXT, extract it only ONCE using its most representative or complete name.
- For the 'label', assign a general category (e.g., Person, Organization, Location, Product, Concept, Event, Artwork, Miscellaneous). Start with broad categories. Consistency in labeling for the same entity across different mentions is important if discernible.
- If possible, provide a brief contextual description for the entity based *only* on the provided CURRENT TEXT. This description MUST be a single sentence and ideally no more than 20 words. If the entity is mentioned multiple times, synthesize this brief, single-sentence description.
- Do NOT extract attributes of entities as separate entities (e.g., for "blue car", extract "car" as an entity, not "blue" as an entity). Qualities like "speed", "demanding tasks", "resolution", "color accuracy", "refresh rate" are generally attributes or characteristics of other entities, not standalone entities themselves, unless the text treats them as a distinct subject or object of discussion.
- Do NOT extract general activities, processes, or verbs as entities unless they are nominalized and treated as distinct concepts in the text (e.g., "The Investigation" if it's a formal named investigation).
- Prioritize concrete entities over highly abstract or overly general concepts unless the text gives them significant focus as standalone items. For example, "customer support response times" is a metric or concept, likely not a distinct entity node on its own unless it's the central subject of a detailed discussion.
- If the text is short and contains no clear entities fitting these criteria, you can return an empty list.
"""

ENTITY_EXTRACTION_USER_PROMPT_TEMPLATE = """
Please extract all distinct entities from the following text content.
If contextual information from previous turns/chunks is provided, use it to help disambiguate or understand the current text, but primarily focus on extracting entities explicitly mentioned or clearly implied in the CURRENT TEXT, adhering to the guidelines.

CONTEXT (Optional, from previous text or related documents):
{context_text}

CURRENT TEXT to extract entities from:
{text_content}
"""

# --- Prompt Templates for Entity Deduplication ---
ENTITY_DEDUPLICATION_SYSTEM_PROMPT = """
You are an expert AI assistant specializing in entity resolution and deduplication.
Your task is to determine if a "New Entity" is a duplicate of any "Existing Entity Candidates" provided.
You also need to suggest the best "canonical_name" and synthesize a "canonical_description" for the entity.
The canonical_description should be concise, informative, and non-redundant, based *only* on the provided descriptions.
"""

ENTITY_DEDUPLICATION_USER_PROMPT_TEMPLATE = """
A "New Entity" has been extracted from a text. We have also found some "Existing Entity Candidates" from our knowledge graph that might be the same as the New Entity based on semantic similarity of their names.

New Entity Details:
- Name: {new_entity_name}
- Label: {new_entity_label}
- Description (from current text): {new_entity_description}

Existing Entity Candidates (if any):
{existing_candidates_json_string} 
{{!-- Each candidate in the JSON string above has 'uuid', 'name', 'label', and 'description' (if available) --}}

Based on all the information provided:
1.  Determine if the "New Entity" refers to the exact same real-world thing as one of the "Existing Entity Candidates".
    - Set `is_duplicate` to true if it is a duplicate, otherwise false.
    - If it is a duplicate, set `duplicate_of_uuid` to the UUID of the existing candidate it matches. If not a duplicate, set `duplicate_of_uuid` to null.

2.  Determine the best `canonical_name` for this entity. This should be the most representative and complete name.

3.  Create a `canonical_description`:
    - If `is_duplicate` is true and a matching `existing_candidate` has a description, synthesize the `new_entity_description` with the `existing_candidate.description`. The goal is a single, coherent, non-redundant description that captures key information from both. If one description is clearly superior or more comprehensive, it can be favored.
    - If `is_duplicate` is true but the matched `existing_candidate` has no description, the `canonical_description` should be based on the `new_entity_description`.
    - If `is_duplicate` is false, the `canonical_description` should be based on the `new_entity_description`.
    - The description should be concise and informative, ideally under 50 words. If the provided descriptions are vague or uninformative, the canonical_description can be null or a very brief summary. Base this *only* on the provided descriptions.

Provide your decision as a JSON object matching the EntityDeduplicationDecision schema.
"""

# --- NEW Prompt Templates for Relationship Extraction ---

RELATIONSHIP_EXTRACTION_SYSTEM_PROMPT = """
You are an expert AI assistant tasked with identifying and extracting factual, directional relationships between a given list of entities, based on the provided text.
The relationships should represent clear interactions, associations, or properties connecting two distinct entities.
"""

RELATIONSHIP_EXTRACTION_USER_PROMPT_TEMPLATE = """
Given the following "CURRENT TEXT" and a list of "IDENTIFIED ENTITIES" (with their names and labels) that were extracted from this text:

CURRENT TEXT:
{text_content}

IDENTIFIED ENTITIES (from the CURRENT TEXT):
{entities_json_string} 
{{!-- Each entity in the JSON string above is an object with "name" and "label" --}}

Task:
Identify and extract all clear, factual, and directional relationships **strictly between pairs of entities listed in "IDENTIFIED ENTITIES"**.

For each relationship, provide:
1.  `source_entity_name`: The exact name of the source entity from the "IDENTIFIED ENTITIES" list.
2.  `target_entity_name`: The exact name of the target entity from the "IDENTIFIED ENTITIES" list. The source and target must be different.
3.  `relation_label`: A concise label for the relationship in SCREAMING_SNAKE_CASE (e.g., VISITED, ATE, IS_FRIEND_OF, POSSESSES, PART_OF, CAUSED_BY, ANNOUNCED_PRODUCT). Be specific but not overly granular. Prefer active voice where possible (e.g., "POOH_ATE_HONEY" rather than "HONEY_WAS_EATEN_BY_POOH" if Pooh is the actor).
4.  `fact_sentence`: A complete, natural language sentence, ideally 30 words or less, that clearly states the relationship between the source and target entity. This sentence should be directly derivable from the "CURRENT TEXT". For example: "Winnie-the-Pooh ate a jar of honey." or "Rabbit owns the house where Pooh got stuck."

Guidelines:
- Only extract relationships where **both the source and target entities are explicitly present by name in the "IDENTIFIED ENTITIES" list provided above.**
- Ensure `source_entity_name` and `target_entity_name` **exactly match** names from the provided "IDENTIFIED ENTITIES" list.
- Do NOT invent entities or use concepts as targets/sources if they are not in the "IDENTIFIED ENTITIES" list. For example, if "Speed" or "Demanding Tasks" are not in the list, do not use them as a source or target.
- Relationships should be directional (source -> target).
- Do not extract attributes of a single entity as a relationship (e.g., "Pooh is a bear" is an attribute/classification, not a relationship between two distinct entities from the provided list unless "Bear" itself was also an identified entity).
- Avoid overly generic labels like "RELATED_TO" if a more specific one applies.
- If multiple sentences in the text describe the same core relationship between the same two entities, synthesize it into one representative `fact_sentence` and a single `relation_label`.
- If no clear relationships meeting these strict criteria are found in the text, return an empty list for "relationships".
"""