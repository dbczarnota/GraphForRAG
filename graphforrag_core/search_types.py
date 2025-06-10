# graphforrag_core/search_types.py
from enum import Enum
from typing import List, Optional, Dict, Any, Literal # Ensure Literal is imported
from pydantic import BaseModel, Field
from .types import FlaggedPropertiesConfig # Explicitly import FlaggedPropertiesConfig

# --- Chunk Search Specific ---
class ChunkSearchMethod(str, Enum):
    KEYWORD = "keyword_fulltext"
    SEMANTIC = "semantic_vector"

class ChunkRerankerMethod(str, Enum):
    RRF = "reciprocal_rank_fusion"

class ChunkSearchConfig(BaseModel):
    search_methods: List[ChunkSearchMethod] = Field(default_factory=lambda: [ChunkSearchMethod.KEYWORD, ChunkSearchMethod.SEMANTIC])
    reranker: ChunkRerankerMethod = ChunkRerankerMethod.RRF
    limit: int = Field(default=10, description="Final number of results to return for this type if min_results is not dominant.")
    min_results: int = Field(default=0, ge=0, description="Minimum number of chunk results to try to include, if available. Overrides 'limit' for this type if necessary to meet this minimum.")
    keyword_fetch_limit: int = Field(default=20)
    semantic_fetch_limit: int = Field(default=20)
    min_similarity_score: float = Field(default=0.7)
    rrf_k: int = Field(default=60)


# --- Entity Search Specific ---
class EntitySearchMethod(str, Enum):
    KEYWORD_NAME = "keyword_name_fulltext"
    SEMANTIC_NAME = "semantic_name_vector"

class EntityRerankerMethod(str, Enum):
    RRF = "reciprocal_rank_fusion"

class EntitySearchConfig(BaseModel):
    search_methods: List[EntitySearchMethod] = Field(default_factory=lambda: [EntitySearchMethod.KEYWORD_NAME, EntitySearchMethod.SEMANTIC_NAME])
    reranker: EntityRerankerMethod = EntityRerankerMethod.RRF
    limit: int = Field(default=10, description="Final number of results to return for this type if min_results is not dominant.")
    min_results: int = Field(default=0, ge=0, description="Minimum number of entity results to try to include, if available.") 
    keyword_fetch_limit: int = Field(default=20)
    semantic_name_fetch_limit: int = Field(default=20)
    min_similarity_score_name: float = Field(default=0.7)
    rrf_k: int = Field(default=60)

# --- Relationship Search Specific ---
class RelationshipSearchMethod(str, Enum):
    KEYWORD_FACT = "keyword_fact_fulltext"
    SEMANTIC_FACT = "semantic_fact_vector"

class RelationshipRerankerMethod(str, Enum):
    RRF = "reciprocal_rank_fusion"

class RelationshipSearchConfig(BaseModel):
    search_methods: List[RelationshipSearchMethod] = Field(
        default_factory=lambda: [RelationshipSearchMethod.KEYWORD_FACT, RelationshipSearchMethod.SEMANTIC_FACT]
    )
    reranker: RelationshipRerankerMethod = RelationshipRerankerMethod.RRF
    limit: int = Field(default=10, description="Final number of results to return for this type if min_results is not dominant.")
    min_results: int = Field(default=0, ge=0, description="Minimum number of relationship results to try to include, if available.")
    keyword_fetch_limit: int = Field(default=20)
    semantic_fetch_limit: int = Field(default=20)
    min_similarity_score: float = Field(default=0.7, description="Minimum similarity score for semantic search on relationship facts.")
    rrf_k: int = Field(default=60)

# --- NEW: Mention Search Specific ---
class MentionSearchMethod(str, Enum):
    KEYWORD_FACT = "keyword_fact_fulltext"
    SEMANTIC_FACT = "semantic_fact_vector"

class MentionRerankerMethod(str, Enum):
    RRF = "reciprocal_rank_fusion"

class MentionSearchConfig(BaseModel):
    search_methods: List[MentionSearchMethod] = Field(
        default_factory=lambda: [MentionSearchMethod.KEYWORD_FACT, MentionSearchMethod.SEMANTIC_FACT]
    )
    reranker: MentionRerankerMethod = MentionRerankerMethod.RRF
    limit: int = Field(default=10, description="Final number of Mention results to return if min_results is not dominant.")
    min_results: int = Field(default=0, ge=0, description="Minimum number of Mention results to try to include, if available.")
    keyword_fetch_limit: int = Field(default=20)
    semantic_fetch_limit: int = Field(default=20)
    min_similarity_score: float = Field(default=0.7, description="Minimum similarity score for semantic search on Mention facts.")
    rrf_k: int = Field(default=60)

# --- NEW: Source Search Specific ---
class SourceSearchMethod(str, Enum):
    KEYWORD_CONTENT = "keyword_content_fulltext"
    SEMANTIC_CONTENT = "semantic_content_vector"

class SourceRerankerMethod(str, Enum):
    RRF = "reciprocal_rank_fusion"

class SourceSearchConfig(BaseModel):
    search_methods: List[SourceSearchMethod] = Field(
        default_factory=lambda: [SourceSearchMethod.KEYWORD_CONTENT, SourceSearchMethod.SEMANTIC_CONTENT]
    )
    reranker: SourceRerankerMethod = SourceRerankerMethod.RRF
    limit: int = Field(default=5, description="Final number of results to return for Source type if min_results is not dominant.")
    min_results: int = Field(default=0, ge=0, description="Minimum number of source results to try to include, if available.")
    keyword_fetch_limit: int = Field(default=10)
    semantic_fetch_limit: int = Field(default=10)
    min_similarity_score: float = Field(default=0.7)
    rrf_k: int = Field(default=60)

# --- General Search Result Structures ---
class SearchResultItem(BaseModel):
    uuid: str
    name: Optional[str] = None 
    content: Optional[str] = None 
    fact_sentence: Optional[str] = None 
    label: Optional[str] = None 
    source_node_uuid: Optional[str] = None 
    target_node_uuid: Optional[str] = None 
    score: float
    result_type: Literal["Chunk", "Entity", "Relationship", "Source", "Product", "Mention"] 
    connected_facts: Optional[List[Dict[str, Any]]] = Field(
        default=None, 
        description="List of connected facts/relationships for Entity or Product nodes. Each fact is a dictionary."
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)

class CombinedSearchResults(BaseModel):
    items: List[SearchResultItem] = Field(default_factory=list)
    query_text: Optional[str] = None
    context_snippet: Optional[str] = Field(default=None, description="A formatted string combining relevant information from search results, suitable for LLM context.")
    source_data_references: Optional[List[SearchResultItem]] = Field(default=None, description="A list of unique Source, Chunk, and Product nodes that contributed to the main search results.")
    source_data_snippet: Optional[str] = Field(default=None, description="A textual snippet derived from the source_data_references.")
    executed_llm_cypher_query: Optional[str] = Field(default=None, description="The LLM-generated Cypher query that was executed, if any.")
    raw_llm_cypher_query_results: Optional[List[Dict[str, Any]]] = Field(default=None, description="Raw list of dictionary results from the executed LLM-generated Cypher query, if any.")
    
        
        
class MultiQueryConfig(BaseModel):
    enabled: bool = Field(default=False, description="Whether to enable Multi-Query Retrieval.")
    include_original_query: bool = Field(
        default=True, 
        description="Whether to include the original user query in the set of queries to be executed for search. If False, only generated alternative queries will be used."
    )
    max_alternative_questions: int = Field(
        default=3, 
        ge=0, # Changed from ge=1 to allow 0 alternatives when include_original_query=True and MQR LLM is used
        le=5, 
        description="Maximum number of alternative questions to generate. If 0, and include_original_query is True, only the original query runs (potentially with specific MQR LLM)."
    )
    mqr_llm_models: Optional[List[str]] = Field(
        default=None,
        description="Optional list of LLM model names (e.g., ['gpt-4o-mini', 'gemini-2.0-flash']) to use specifically for MQR generation. If None, uses the default LLM client of the MultiQueryGenerator service."
    )

class CypherSearchConfig(BaseModel):
    """Configuration for LLM-generated Cypher search."""
    enabled: bool = Field(default=False, description="Whether to enable LLM-generated Cypher search.")
    llm_models: Optional[List[str]] = Field(
        default=None,
        description="Optional list of LLM model names to use specifically for Cypher query generation. If None, uses a default LLM setup."
    )
    flagged_properties_config: Optional[FlaggedPropertiesConfig] = Field( 
        default=None,
        description="Optional configuration for flagging properties to include their distinct values in the schema provided to the Cypher generation LLM."
    )
    # Placeholder for future: custom_prompt_template: Optional[str] = None

CypherSearchConfig.model_rebuild() # Resolve forward references

# --- NEW: Product Search Specific ---
class ProductSearchMethod(str, Enum):
    KEYWORD_NAME_CONTENT = "keyword_name_content_fulltext"
    SEMANTIC_NAME = "semantic_name_vector"
    SEMANTIC_CONTENT = "semantic_content_vector"

class ProductRerankerMethod(str, Enum):
    RRF = "reciprocal_rank_fusion"

class ProductSearchConfig(BaseModel):
    search_methods: List[ProductSearchMethod] = Field(
        default_factory=lambda: [
            ProductSearchMethod.KEYWORD_NAME_CONTENT,
            ProductSearchMethod.SEMANTIC_NAME,
            ProductSearchMethod.SEMANTIC_CONTENT,
        ]
    )
    reranker: ProductRerankerMethod = ProductRerankerMethod.RRF
    limit: int = Field(default=5, description="Final number of results to return for Product type if min_results is not dominant.")
    min_results: int = Field(default=0, ge=0, description="Minimum number of product results to try to include, if available.")
    keyword_fetch_limit: int = Field(default=10)
    semantic_name_fetch_limit: int = Field(default=10)
    semantic_content_fetch_limit: int = Field(default=10)
    min_similarity_score_name: float = Field(default=0.7)
    min_similarity_score_content: float = Field(default=0.65)
    rrf_k: int = Field(default=60)
    
    
class SearchConfig(BaseModel):
    chunk_config: Optional[ChunkSearchConfig] = Field(default_factory=ChunkSearchConfig)
    entity_config: Optional[EntitySearchConfig] = Field(default_factory=EntitySearchConfig)
    relationship_config: Optional[RelationshipSearchConfig] = Field(default_factory=RelationshipSearchConfig)
    source_config: Optional[SourceSearchConfig] = Field(default_factory=SourceSearchConfig) 
    product_config: Optional[ProductSearchConfig] = Field(default_factory=ProductSearchConfig) 
    mention_config: Optional[MentionSearchConfig] = Field(default_factory=MentionSearchConfig) 
    mqr_config: Optional[MultiQueryConfig] = Field(default=None, description="Configuration for Multi-Query Retrieval. If None, MQR is disabled.")
    cypher_search_config: Optional[CypherSearchConfig] = Field(default=None, description="Configuration for LLM-generated Cypher search. If None, this search type is disabled.") # NEW
    overall_results_limit: Optional[int] = Field(
        default=10, 
        ge=1, 
        description="Optional overall limit for the final number of results returned by the combined search. Applied after aggregation and sorting."
    )