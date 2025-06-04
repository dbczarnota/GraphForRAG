# config/llm_prompts.py
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal # Added Dict

# --- Pydantic Models for LLM Output (Entity Extraction) ---
class ExtractedEntity(BaseModel):
    name: str = Field(..., description="The clearly identified and most complete/canonical name of the entity as found or inferred from the text. Should be specific and unambiguous (e.g., full names if available).")
    label: str = Field(default="GenericEntity", description="A general ontological label for the entity (e.g., Person, Organization, Location, Product, Concept). Start with broad categories.")
    fact_sentence_about_mention: Optional[str] = Field(default=None, description="A brief, single-sentence statement describing the entity or its role/action in the context of the CURRENT TEXT, derived directly from its mention. Max 20 words. This will become the 'fact_sentence' on the MENTIONS relationship.")

class ExtractedEntitiesList(BaseModel):
    entities: List[ExtractedEntity] = Field(default_factory=list, description="A list of unique entities found in the text.")

# --- Pydantic Models for LLM Output (Entity Deduplication) ---
class ExistingEntityCandidate(BaseModel):
    uuid: str
    name: str
    label: str 
    node_type: Literal["Entity", "Product"] 
    score: Optional[float] = None 
    existing_mention_facts: Optional[List[str]] = Field(default=None, description="A list of example fact sentences from previous MENTIONS relationships for this candidate, if available.") # ADDED


class EntityDeduplicationDecision(BaseModel):
    is_duplicate: bool = Field(..., description="True if the new entity is considered a duplicate of one of the existing candidates, False otherwise.")
    duplicate_of_uuid: Optional[str] = Field(default=None, description="The UUID of the existing candidate that the new entity is a duplicate of. Null if not a duplicate.")
    canonical_name: str = Field(..., description="The suggested canonical/best name for this entity (either the new entity's name or an existing candidate's name, or a combined/improved version).")
    # canonical_description: Optional[str] = Field(default=None, description="A synthesized, concise, and informative description for the entity, incorporating information from the new mention and any existing description if it's a duplicate. Should be based SOLELY on provided descriptions.") # REMOVED
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

# --- Pydantic Models for LLM Output (Multi-Query Retrieval) ---
class AlternativeQuery(BaseModel):
    query: str = Field(..., description="An alternative user query based on the original.")

class AlternativeQueriesList(BaseModel):
    alternative_queries: List[AlternativeQuery] = Field(
        default_factory=list, 
        description="A list of alternative queries generated to help retrieve relevant data. Should not include the original query."
    )
    
# --- Pydantic Models for LLM Output (Entity Deduplication) ---


    
# --- Pydantic Models for LLM Output (Product-Entity Matching for Promotion) ---
class ProductEntityMatchDecision(BaseModel):
    is_strong_match: bool = Field(..., description="True if the new product data is considered a strong match for an existing Entity, indicating a promotion/replacement is suitable.")
    matched_entity_uuid: Optional[str] = Field(default=None, description="The UUID of the existing Entity that the new product data matches. Null if not a strong match.")
    
            
# --- Prompt Templates for Entity Extraction ---
ENTITY_EXTRACTION_SYSTEM_PROMPT = """
You are an expert AI assistant tasked with identifying and extracting named entities from the provided text.
Your goal is to identify distinct real-world objects, concepts that are treated as subjects/objects, persons, organizations, locations, products, etc., and represent them consistently.

Guidelines:
- Focus on extracting nouns or noun phrases that represent distinct, tangible or clearly defined conceptual entities.
- For each entity, provide the most complete and canonical name possible based on the information in the CURRENT TEXT. For example, if "Mr. John Smith" and "Smith" refer to the same person in the text, use "John Smith". If only "Pooh" is mentioned, use "Pooh", but if "Winnie-the-Pooh" is mentioned, prefer that.
- If an entity is mentioned multiple times in the CURRENT TEXT, extract it only ONCE using its most representative or complete name.
- For the 'label', assign a general category (e.g., Person, Organization, Location, Product, Concept, Event, Artwork, Miscellaneous). Start with broad categories. Consistency in labeling for the same entity across different mentions is important if discernible.
- For 'fact_sentence_about_mention': Generate a concise, single-sentence definition or description of the entity, answering the question "What is [Entity Name]?" or "Who is [Entity Name]?" based *only* on its context in the CURRENT TEXT. This sentence should be factual and directly derivable. Max 20 words. Example: If text says "Rabbit, a good host, offered Pooh honey", for Rabbit, it could be "Rabbit is a good host who offered Pooh honey." For Pooh, it could be "Pooh is a character who likes honey." This statement will be stored as the fact_sentence on the MENTIONS relationship.
- Do NOT extract attributes of entities as separate entities (e.g., for "blue car", extract "car" as an entity, not "blue" as an entity). Qualities like "speed", "demanding tasks", "resolution", "color accuracy", "refresh rate" are generally attributes or characteristics of other entities, not standalone entities themselves, unless the text treats them as a distinct subject or object of discussion.
- Do NOT extract general activities, processes, or verbs as entities unless they are nominalized and treated as distinct concepts in the text (e.g., "The Investigation" if it's a formal named investigation).
- Prioritize concrete entities over highly abstract or overly general concepts unless the text gives them significant focus as standalone items. For example, "customer support response times" is a metric or concept, likely not a distinct entity node on its own unless it's the central subject of a detailed discussion.
- If the text is short and contains no clear entities fitting these criteria, you can return an empty list.
"""

ENTITY_EXTRACTION_USER_PROMPT_TEMPLATE = """
Please extract all distinct entities from the following text content.
For each entity, provide its name, a suitable label, and a 'fact_sentence_about_mention' as per the system guidelines (a concise definition/description answering "What/Who is [Entity Name]?" based on the text).
If contextual information from previous turns/chunks is provided, use it to help disambiguate or understand the current text, but primarily focus on extracting entities explicitly mentioned or clearly implied in the CURRENT TEXT, adhering to the guidelines.

CONTEXT (Optional, from previous text or related documents):
{context_text}

CURRENT TEXT to extract entities from:
{text_content}
"""

ENTITY_DEDUPLICATION_SYSTEM_PROMPT = """
You are an expert AI assistant specializing in entity resolution and deduplication.
Your task is to determine if a "New Entity" (identified by its name and label from a text segment) is a duplicate of any "Existing Entity Candidates" provided from a knowledge graph.
You also need to suggest the best "canonical_name" for the entity if a match is found or if the new entity's name needs refinement.
The primary basis for matching should be the entity names and their labels. Contextual statements or previous descriptions are for your understanding but not for synthesizing a new canonical description on the entity itself.
"""

ENTITY_DEDUPLICATION_USER_PROMPT_TEMPLATE = """
A "New Entity" has been extracted from a text. We have also found some "Existing Entity Candidates" from our knowledge graph that might be the same as the New Entity based on semantic similarity of their names.
These candidates can be either:
- 'Entity': A general concept, person, organization, etc., previously mentioned.
- 'Product': A canonical product definition from a catalog or specific product data.

New Entity Details (extracted from current text):
- Name: {new_entity_name}
- Label: {new_entity_label}
- Fact Sentence about this Mention (from current text, for your context when considering the new entity): {new_entity_fact_sentence_about_mention}

Existing Entity Candidates (if any):
{existing_candidates_json_string} 
{{!-- Each candidate in the JSON string above has 'uuid', 'name', 'label' (specific type like 'Person' or 'Laptop'), 'node_type' ('Entity' or 'Product'). They will also have 'existing_mention_facts' if available. --}}

Task:
1.  Determine if the "New Entity" refers to the exact same real-world thing as one of the "Existing Entity Candidates".
    - Base this primarily on the `name` and `label` of the new entity and the candidates. Consider `existing_mention_facts` for additional context about existing candidates.
    - If the New Entity seems to be a product and a matching "Product" candidate exists, prefer matching to the "Product" candidate.
    - Set `is_duplicate` to true if it is a duplicate, otherwise false.
    - If it is a duplicate, set `duplicate_of_uuid` to the UUID of the existing candidate it matches. If not a duplicate, set `duplicate_of_uuid` to null.

2.  Determine the best `canonical_name` for this entity. This should be the most representative and complete name (e.g., if the new entity name is "Dell XPS" and an existing candidate is "Dell XPS 13 (2024)", the latter might be more canonical). If matching a "Product" candidate, the Product's name is usually canonical. If not a duplicate, the canonical_name is typically the new_entity_name unless minor refinement is obvious.

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


# --- Prompt Templates for Multi-Query Retrieval (MQR) ---
MULTI_QUERY_GENERATION_SYSTEM_PROMPT = """
You are an expert AI assistant highly skilled in query understanding and reformulation for retrieval systems. 
Your task is to generate alternative queries based on the user's original query to improve the chances of finding relevant information in a vector database.
Adhere strictly to the formatting instructions and the user's language.
The goal is to explore different phrasings, sub-topics, or perspectives related to the original query.
Do not include the original query in your list of alternative_queries.
"""

MULTI_QUERY_GENERATION_USER_PROMPT_TEMPLATE = """
Based on the "Original User Query" below, generate up to {max_alternative_questions} alternative user queries.
These alternative queries should help retrieve a more diverse and comprehensive set of relevant documents from a vector database.

Guidelines:
- **If the user’s original query references multiple distinct entities or concepts**, ensure that:
    - At least one, and ideally the first one or two, alternative queries rephrase the original query to capture the combined intent, possibly using synonyms or different sentence structures.
    - Subsequent alternative queries can break down the original query by focusing on individual entities/concepts or different aspects/perspectives of the original query. For example, if the original query is "Compare the performance of Dell XPS 13 and MacBook Air M3 for students", alternatives could be "Student experiences with Dell XPS 13" and "MacBook Air M3 suitability for college work".
- **If the user’s original query includes specific dates, times, or numerical values**, try to incorporate these accurately into relevant alternative queries or generate queries that explore related timeframes or values if appropriate.
- **Maintain the original language** used by the user in all generated alternative queries.
- **Focus on semantic alternatives**: Think about different ways someone might ask for the same or related information.
- **Generate distinct queries**: Each alternative query should offer a unique angle or phrasing.
- **Do NOT include the original query itself in the list of `alternative_queries` you generate.**

Original User Query:
"{original_user_query}"

Current date (for context, if relevant to the query): {current_date}
Current day of the week (for context, if relevant, e.g., for "tomorrow", "yesterday"): {current_day_of_a_week}

Generate the alternative queries.
"""

# --- Prompt Templates for Product-Entity Matching (Promotion) ---
PRODUCT_ENTITY_MATCH_SYSTEM_PROMPT = """
You are an expert AI assistant specializing in entity matching and disambiguation.
Your task is to determine if "New Product Data" (which will be used to create a canonical Product node)
is a strong match for an "Existing Entity Candidate" that was previously extracted from general text.
A strong match means they refer to the exact same real-world product, and the existing Entity should be replaced/upgraded by the new Product data.
"""

PRODUCT_ENTITY_MATCH_USER_PROMPT_TEMPLATE = """
We are about to ingest "New Product Data" which will create a formal Product node in our knowledge graph.
We found an "Existing Entity Candidate" (type :Entity) that might represent the same product, but was extracted from general text and might be less complete.

New Product Data (summary):
- Name: {new_product_name}
- Product Content (this is the raw data, e.g., JSON string, providing rich details): {new_product_description} 
- Key Attributes (extracted from product data for easier comparison): {new_product_attributes_json_string}

Existing Entity Candidate (extracted from text, has no direct overall description):
- UUID: {existing_entity_uuid}
- Name: {existing_entity_name}
- Label: {existing_entity_label}
- Note: Contextual statements about this entity from various text mentions are stored on its MENTIONS relationships, not as a single description on the entity itself. Your matching should primarily focus on name, label, and the details provided for the "New Product Data".

Based on all the information provided, determine if the "New Product Data" is a **strong and unambiguous match** for the "Existing Entity Candidate".
This means you are highly confident they refer to the exact same specific product.
- If it's a strong match, set `is_strong_match` to true, and `matched_entity_uuid` to the UUID of the Existing Entity Candidate.
- If it's not a strong match (e.g., different products, related but not identical, or insufficient information for high confidence), set `is_strong_match` to false.

Provide your decision as a JSON object matching the ProductEntityMatchDecision schema.
"""