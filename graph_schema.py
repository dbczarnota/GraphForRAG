from langchain_neo4j import Neo4jVector
from langchain_neo4j import Neo4jGraph
from dotenv import load_dotenv
import os
import logging
import logging
from rich import traceback
from rich.logging import RichHandler
import textwrap
import asyncio
from graphforrag_core.graphforrag import GraphForRAG
from graphforrag_core.openai_embedder import OpenAIEmbedder, OpenAIEmbedderConfig
from graphforrag_core.types import FlaggedPropertiesConfig, PropertyValueConfig

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s", 
    datefmt="%Y-%m-%d %H:%M:%S", 
    handlers=[RichHandler(rich_tracebacks=True, markup=True, show_path=False, log_time_format="[%X.%f]")],
)
logger = logging.getLogger("graph_schema") 

schema_set = """
Node properties:
Chunk {
  characters_present: LIST
  chunk_number: INTEGER
  content: STRING
  content_embedding: LIST
  created_at: DATE_TIME
  entity_count: INTEGER
  interaction_type: STRING
  keywords: LIST
  name: STRING
  problem: STRING
  relationship_count: INTEGER
  resolution_pending: STRING
  setting: STRING
  setting_detail: STRING
  source_description: STRING
  theme: STRING
  uuid: STRING
}
Entity {
  created_at: DATE_TIME
  label: STRING
  name: STRING
  name_embedding: LIST
  normalized_name: STRING
  updated_at: DATE_TIME
  uuid: STRING
}
Product {
  available_colors: LIST
  brand: STRING
  category: STRING
  chassis_material: STRING
  content: STRING
  content_embedding: LIST
  cooling_system_type: STRING
  created_at: DATE_TIME
  current_availability_status: STRING
  display_panel_type: STRING
  display_refresh_rate_hz: INTEGER
  display_tech: STRING
  editor_rating_numeric: FLOAT
  features_list: LIST
  gpu_model: STRING
  internal_product_id: STRING
  key_technical_specs: LIST
  keyboard_accessory_separate: BOOLEAN
  name: STRING
  name_embedding: LIST
  operating_system_version: STRING
  os_included: STRING
  pen_compatibility: STRING
  price: FLOAT
  release_year: INTEGER
  review_score_techradar_numeric: FLOAT
  sku: STRING
  target_audience_tags: LIST
  technical_specs: STRING
  updated_at: DATE_TIME
  uuid: STRING
}
Source {
  author: STRING
  catalog_version: STRING
  category: STRING
  content: STRING
  content_embedding: LIST
  created_at: DATE_TIME
  name: STRING
  original_publication_year: INTEGER
  prepared_by: STRING
  publication_date: STRING
  region: STRING
  release_date: STRING
  uuid: STRING
  version: STRING
}

Relationship properties:
BELONGS_TO_SOURCE {
  created_at: DATE_TIME
}
MENTIONS {
  created_at: DATE_TIME
  fact_embedding: LIST
  fact_sentence: STRING
  source_chunk_uuid: STRING
  uuid: STRING
}
NEXT_CHUNK {
  created_at: DATE_TIME
}
RELATES_TO {
  created_at: DATE_TIME
  fact_embedding: LIST
  fact_sentence: STRING
  relation_label: STRING
  source_chunk_uuid: STRING
  uuid: STRING
}

The relationships:
(Chunk)-[:BELONGS_TO_SOURCE]->(Source)
(Chunk)-[:MENTIONS]->(Entity)
(Chunk)-[:MENTIONS]->(Product)
(Chunk)-[:NEXT_CHUNK]->(Chunk)
(Entity)-[:RELATES_TO]->(Entity)
(Entity)-[:RELATES_TO]->(Product)
(Product)-[:BELONGS_TO_SOURCE]->(Source)
(Product)-[:RELATES_TO]->(Entity)
"""
async def main():

    load_dotenv()
    NEO4J_URI = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
    NEO4J_USER = os.environ.get('NEO4J_USER', 'neo4j')
    NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD', 'password')
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")


    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not found in environment variables. Cannot initialize OpenAIEmbedder.")
        return

    graph_for_rag_instance = None # For finally block
    try:
        # Setup embedder for GraphForRAG initialization
        embedder_config = OpenAIEmbedderConfig(api_key=OPENAI_API_KEY) # Default or your specific config
        openai_embedder = OpenAIEmbedder(config=embedder_config)

        example_flagged_config_for_graph_schema = FlaggedPropertiesConfig(
            nodes={
                "Product": {"category": PropertyValueConfig(limit=3)},
            }
        )

        graph_for_rag_instance = GraphForRAG(
            uri=NEO4J_URI,
            user=NEO4J_USER,
            password=NEO4J_PASSWORD,
            embedder_client=openai_embedder, # Pass the embedder
            default_schema_flagged_properties_config=example_flagged_config_for_graph_schema # Pass the new config
        )
        
        logger.info("SCHEMA (from GraphForRAG.get_schema()):")
        schema_string = await graph_for_rag_instance.get_schema()
        logger.info(textwrap.fill(schema_string, 120)) # Wider fill for potentially long lines

        logger.info("\n--- Testing Cypher Query Generation ---")
        
        # Example question
        user_question_for_cypher = "Find cheap Dell laptops for students."

        # 1. Generate Cypher with dynamically fetched schema (using G4R's default schema manager config)
        logger.info(f"\n1. Generating Cypher for question: '{user_question_for_cypher}' (using dynamic schema)")
        if graph_for_rag_instance.cypher_generator: # Access via property
            # The CypherGenerator instance from GraphForRAG uses the flagged_properties_config
            # that GraphForRAG was initialized with for its SchemaManager.
            # If a specific LLM for Cypher generation is needed, it should be configured
            # when GraphForRAG initializes its CypherGenerator, or CypherGenerator 
            # could be reconfigured/re-instantiated here with specific models if needed.
            # For this example, we use the default from G4R.
            generated_query_dynamic, usage_dynamic = await graph_for_rag_instance.cypher_generator.generate_cypher_query(
                question=user_question_for_cypher
                # custom_schema_string is None by default, so it uses schema_manager
            )
            if generated_query_dynamic:
                logger.info(f"Dynamically Generated Cypher:\n{generated_query_dynamic}")
                if usage_dynamic: logger.info(f"Dynamic Gen Usage: {usage_dynamic.total_tokens} tokens")
            else:
                logger.warning("Failed to generate Cypher query using dynamic schema.")
        else:
            logger.error("GraphForRAG instance does not have a CypherGenerator.")

        # 2. Generate Cypher with a custom schema string
        logger.info(f"\n2. Generating Cypher for question: '{user_question_for_cypher}' (using custom schema)")
        custom_test_schema = """Node properties:
Product {name: STRING, category: STRING {possible values: {Laptop, Desktop}}, price: FLOAT, brand: STRING {possible values: {Dell, Apple, HP}}}
Student {name: STRING, budget: FLOAT}
Relationship properties:
SUITABLE_FOR {}
MENTIONS {}
The relationships:
(Chunk)-[:MENTIONS]->(Product)
(Product)-[:SUITABLE_FOR]->(Student)
(Entity)-[:RELATES_TO]->(Entity)""" # Note: I corrected a slight syntax issue in your example custom schema (removed extra (Entity)-[:RELATES_TO]->(Entity)) if that was unintentional, if not, it's fine.

        if graph_for_rag_instance.cypher_generator:
            # We'll use the same CypherGenerator instance from GraphForRAG,
            # but pass the custom_schema_string to its generate_cypher_query method.
            generated_query_custom, usage_custom = await graph_for_rag_instance.cypher_generator.generate_cypher_query(
                question=user_question_for_cypher,
                custom_schema_string=custom_test_schema
            )
            if generated_query_custom:
                logger.info(f"Custom Schema Generated Cypher:\n{generated_query_custom}")
                if usage_custom: logger.info(f"Custom Gen Usage: {usage_custom.total_tokens} tokens")
            else:
                logger.warning("Failed to generate Cypher query using custom schema.")
        else:
            logger.error("GraphForRAG instance does not have a CypherGenerator for custom schema test.")

    except Exception as e_main:
        logger.error(f"An error occurred in graph_schema.py main: {e_main}", exc_info=True)
    finally:
        if graph_for_rag_instance:
            await graph_for_rag_instance.close()
    
    
if __name__ == "__main__":
    asyncio.run(main())