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
from graphforrag_core.schema_manager import get_schema

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s", 
    datefmt="%Y-%m-%d %H:%M:%S", 
    handlers=[RichHandler(rich_tracebacks=True, markup=True, show_path=False, log_time_format="[%X.%f]")],
)
logger = logging.getLogger("graph_schema") 

schema_set = """
Node properties:
Chunk {uuid: STRING, content: STRING, name: STRING, source_description: STRING, created_at: DATE_TIME, entity_count: INTEGER, relationship_count: INTEGER, chunk_number: INTEGER,      
keywords: LIST, content_embedding: LIST, characters_present: LIST, interaction_type: STRING, setting: STRING, theme: STRING, problem: STRING, setting_detail: STRING,
resolution_pending: STRING}
Source {uuid: STRING, content: STRING, name: STRING, created_at: DATE_TIME, region: STRING, release_date: STRING, content_embedding: LIST, catalog_version: STRING, prepared_by:       
STRING, category: STRING, author: STRING, original_publication_year: INTEGER, version: STRING, publication_date: STRING}
Entity {uuid: STRING, name: STRING, created_at: DATE_TIME, label: STRING, name_embedding: LIST, updated_at: DATE_TIME, normalized_name: STRING}
Product {uuid: STRING, content: STRING, name: STRING, created_at: DATE_TIME, category: STRING, price: FLOAT, sku: STRING, content_embedding: LIST, name_embedding: LIST, updated_at:   
DATE_TIME, release_year: INTEGER, brand: STRING, features_list: LIST, editor_rating_numeric: FLOAT, target_audience_tags: LIST, technical_specs: STRING, internal_product_id: STRING,  
available_colors: LIST, review_score_techradar_numeric: FLOAT, key_technical_specs: LIST, chassis_material: STRING, os_included: STRING, keyboard_accessory_separate: BOOLEAN,
operating_system_version: STRING, display_tech: STRING, pen_compatibility: STRING, display_refresh_rate_hz: INTEGER, current_availability_status: STRING, display_panel_type: STRING,  
cooling_system_type: STRING, gpu_model: STRING}
Relationship properties:
NEXT_CHUNK {created_at: DATE_TIME}
BELONGS_TO_SOURCE {created_at: DATE_TIME}
RELATES_TO {uuid: STRING, created_at: DATE_TIME, relation_label: STRING, fact_embedding: LIST, fact_sentence: STRING, source_chunk_uuid: STRING}
MENTIONS {uuid: STRING, created_at: DATE_TIME, fact_embedding: LIST, fact_sentence: STRING, source_chunk_uuid: STRING}
The relationships:
(:Chunk)-[:NEXT_CHUNK]->(:Chunk)
(:Chunk)-[:MENTIONS]->(:Entity)
(:Chunk)-[:MENTIONS]->(:Product)
(:Chunk)-[:BELONGS_TO_SOURCE]->(:Source)
(:Entity)-[:RELATES_TO]->(:Entity)
(:Entity)-[:RELATES_TO]->(:Product)
(:Product)-[:BELONGS_TO_SOURCE]->(:Source)
(:Product)-[:RELATES_TO]->(:Entity)
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

    kg = Neo4jGraph(url=NEO4J_URI, username=NEO4J_USER, password=NEO4J_PASSWORD)

    kg.refresh_schema()
    logger.info("SCHEMA:")
    logger.info(textwrap.fill(kg.schema, 60))
    
    schema = get_schema(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD)
    logger.info("SCHEMA2:")
    logger.info(schema)
    
    
if __name__ == "__main__":
    asyncio.run(main())