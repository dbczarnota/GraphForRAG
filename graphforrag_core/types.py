# graphforrag_core/types.py
from pydantic import BaseModel, Field
from typing import List, Optional, Dict

class ResolvedEntityInfo(BaseModel):
    uuid: str
    name: str 
    label: str
    
class IngestionConfig(BaseModel):
    """
    Configuration settings for the data ingestion process, particularly for LLM model selection
    used by services like EntityExtractor, EntityResolver, and RelationshipExtractor during ingestion.
    """
    ingestion_llm_models: Optional[List[str]] = Field(
        default=None, 
        description="Optional list of LLM model names (e.g., ['gpt-4o-mini', 'gemini-2.0-flash']) to use specifically for "
                    "ALL LLM-dependent services during data ingestion (EntityExtractor, EntityResolver, RelationshipExtractor). "
                    "If None, these services will use the LLM client passed to GraphForRAG or set up their own defaults."
    )
    # --- Start of new code ---
    extractable_entity_labels: Optional[List[str]] = Field(
        default=None,
        description="Optional list of specific entity labels (e.g., ['Person', 'Product', 'Organization']) to focus on during entity extraction. "
                    "If None or empty, general entity extraction is performed based on the default prompt."
    )
    
    extractable_entity_labels: Optional[List[str]] = Field(
        default=None,
        description="Optional list of specific entity labels (e.g., ['Person', 'Product', 'Organization']) to focus on during entity extraction. "
                    "If None or empty, general entity extraction is performed based on the default prompt."
    )

class PropertyValueConfig(BaseModel):
    """Configuration for fetching distinct values for a property."""
    limit: int = Field(default=10, ge=1, description="Maximum number of distinct values to fetch for this property.")

class FlaggedPropertiesConfig(BaseModel):
    """Configuration for flagging properties to include their distinct values in the schema."""
    nodes: Dict[str, Dict[str, PropertyValueConfig]] = Field(
        default_factory=dict,
        description="Node properties to flag. Format: {NodeLabel: {PropertyName: PropertyValueConfig}}"
    )
    relationships: Dict[str, Dict[str, PropertyValueConfig]] = Field(
        default_factory=dict,
        description="Relationship properties to flag. Format: {RelationshipType: {PropertyName: PropertyValueConfig}}"
    )