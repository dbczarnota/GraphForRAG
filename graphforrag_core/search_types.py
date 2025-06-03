# graphforrag_core/search_types.py
from enum import Enum
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field

# --- Chunk Search Specific ---
# ... (ChunkSearchMethod, ChunkRerankerMethod, ChunkSearchConfig remain the same) ...
class ChunkSearchMethod(str, Enum):
    KEYWORD = "keyword_fulltext"
    SEMANTIC = "semantic_vector"

class ChunkRerankerMethod(str, Enum):
    RRF = "reciprocal_rank_fusion"

class ChunkSearchConfig(BaseModel):
    search_methods: List[ChunkSearchMethod] = Field(default_factory=lambda: [ChunkSearchMethod.KEYWORD, ChunkSearchMethod.SEMANTIC])
    reranker: ChunkRerankerMethod = ChunkRerankerMethod.RRF
    limit: int = Field(default=10, description="Final number of results to return for this type.")
    keyword_fetch_limit: int = Field(default=20)
    semantic_fetch_limit: int = Field(default=20)
    min_similarity_score: float = Field(default=0.7)
    rrf_k: int = Field(default=60)


# --- Entity Search Specific ---
# ... (EntitySearchMethod, EntityRerankerMethod, EntitySearchConfig remain the same) ...
class EntitySearchMethod(str, Enum):
    KEYWORD_NAME_DESC = "keyword_name_description_fulltext"
    SEMANTIC_NAME = "semantic_name_vector"
    SEMANTIC_DESCRIPTION = "semantic_description_vector"

class EntityRerankerMethod(str, Enum):
    RRF = "reciprocal_rank_fusion"

class EntitySearchConfig(BaseModel):
    search_methods: List[EntitySearchMethod] = Field(default_factory=lambda: [EntitySearchMethod.KEYWORD_NAME_DESC, EntitySearchMethod.SEMANTIC_NAME, EntitySearchMethod.SEMANTIC_DESCRIPTION])
    reranker: EntityRerankerMethod = EntityRerankerMethod.RRF
    limit: int = Field(default=10, description="Final number of results to return for this type.")
    keyword_fetch_limit: int = Field(default=20)
    semantic_name_fetch_limit: int = Field(default=20)
    semantic_description_fetch_limit: int = Field(default=20)
    min_similarity_score_name: float = Field(default=0.7)
    min_similarity_score_description: float = Field(default=0.65)
    rrf_k: int = Field(default=60)

# --- NEW: Relationship Search Specific ---
class RelationshipSearchMethod(str, Enum):
    KEYWORD_FACT = "keyword_fact_fulltext"
    SEMANTIC_FACT = "semantic_fact_vector"

class RelationshipRerankerMethod(str, Enum):
    RRF = "reciprocal_rank_fusion"
    # Add more later: CROSS_ENCODER

class RelationshipSearchConfig(BaseModel):
    search_methods: List[RelationshipSearchMethod] = Field(
        default_factory=lambda: [RelationshipSearchMethod.KEYWORD_FACT, RelationshipSearchMethod.SEMANTIC_FACT]
    )
    reranker: RelationshipRerankerMethod = RelationshipRerankerMethod.RRF
    limit: int = Field(default=10, description="Final number of results to return for this type.")
    keyword_fetch_limit: int = Field(default=20)
    semantic_fetch_limit: int = Field(default=20)
    min_similarity_score: float = Field(default=0.7, description="Minimum similarity score for semantic search on relationship facts.")
    rrf_k: int = Field(default=60)

# --- Overall Search Configuration ---
class SearchConfig(BaseModel):
    chunk_config: Optional[ChunkSearchConfig] = Field(default_factory=ChunkSearchConfig)
    entity_config: Optional[EntitySearchConfig] = Field(default_factory=EntitySearchConfig)
    relationship_config: Optional[RelationshipSearchConfig] = Field(default_factory=RelationshipSearchConfig) # <-- ADDED

# --- General Search Result Structures ---
class SearchResultItem(BaseModel):
    uuid: str
    name: Optional[str] = None # For Entities, Chunks (chunk name), Relationships (relation_label)
    content: Optional[str] = None # For Chunks (page_content)
    description: Optional[str] = None # For Entities
    fact_sentence: Optional[str] = None # For Relationships
    label: Optional[str] = None # For Entities
    source_entity_uuid: Optional[str] = None # For Relationships
    target_entity_uuid: Optional[str] = None # For Relationships
    score: float
    result_type: Literal["Chunk", "Entity", "Relationship"]
    metadata: Dict[str, Any] = Field(default_factory=dict)

class CombinedSearchResults(BaseModel):
    items: List[SearchResultItem] = Field(default_factory=list)
    query_text: Optional[str] = None