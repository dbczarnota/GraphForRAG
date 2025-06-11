# main.py
from graphforrag_core.graphforrag import GraphForRAG
from graphforrag_core.openai_embedder import OpenAIEmbedder, OpenAIEmbedderConfig
from data.source_data import source_data_sets 
from graphforrag_core.search_types import (
    SearchConfig, 
    ChunkSearchConfig, ChunkSearchMethod, 
    EntitySearchConfig, EntitySearchMethod, 
    RelationshipSearchConfig, RelationshipSearchMethod, 
    SourceSearchConfig, SourceSearchMethod, 
    ProductSearchConfig, ProductSearchMethod, 
    MentionSearchConfig, MentionSearchMethod, # ADDED MentionSearchConfig, MentionSearchMethod
    CombinedSearchResults, SearchResultItem,
    MultiQueryConfig, CypherSearchConfig
)
from graphforrag_core.types import IngestionConfig, FlaggedPropertiesConfig, PropertyValueConfig
from dotenv import load_dotenv
import os
import logging
from rich import traceback
from rich.logging import RichHandler
from datetime import datetime 
import time 
import asyncio
from typing import List, Dict, Any, Optional 
from config.custom_schema import CUSTOM_SHEMA_STRING

# Ensure logging is at DEBUG for search_manager to see detailed logs
# logging.getLogger("graph_for_rag.search_manager").setLevel(logging.DEBUG)
# logging.getLogger("graph_for_rag.graphforrag").setLevel(logging.DEBUG) 
# logging.getLogger("graph_for_rag.multi_query_generator").setLevel(logging.DEBUG) 
# logging.getLogger("llm_models").setLevel(logging.INFO) 
logging.getLogger("graph_for_rag.schema").setLevel(logging.DEBUG)

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s", 
    datefmt="%Y-%m-%d %H:%M:%S", 
    handlers=[RichHandler(rich_tracebacks=True, markup=True, show_path=False, log_time_format="[%X.%f]")],
)
logger = logging.getLogger("graph_for_rag_main") 
traceback.install()


def get_current_time_ms() -> str:
    return datetime.now().isoformat(sep=' ', timespec='milliseconds')

async def main():
    logger.info(f"[bold cyan]Main execution started at: {get_current_time_ms()}[/bold cyan]")
    main_start_time = time.perf_counter() 
    timings: Dict[str, float] = {}

    section_start_time = time.perf_counter()
    load_dotenv()
    NEO4J_URI = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
    NEO4J_USER = os.environ.get('NEO4J_USER', 'neo4j')
    NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD', 'password')
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
    timings["env_setup"] = (time.perf_counter() - section_start_time) * 1000

    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not found in environment variables. Cannot initialize OpenAIEmbedder.")
        return

    graph = None
    try:
        section_start_time = time.perf_counter()
        embedder_config = OpenAIEmbedderConfig(
            api_key=OPENAI_API_KEY,
            model_name="text-embedding-3-small",
            embedding_dimension=768
        )
        openai_embedder = OpenAIEmbedder(config=embedder_config)
        timings["embedder_init"] = (time.perf_counter() - section_start_time) * 1000

        graph_init_overall_start_time = time.perf_counter()
        logger.info("MAIN: Initializing GraphForRAG instance (LLM client will be set up on demand by services)...")
        
        # Define ingestion config (example)
        ingestion_llm_config = IngestionConfig(
            ingestion_llm_models=["gpt-4.1-mini", "gemini-2.0-flash"],
            # extractable_entity_labels=["Product", "Brand", "Concept", "Company", "Person/Character", "Location"] # Example: Use only gpt-4o-mini for all ingestion tasks
            # ingestion_llm_models=[] # Example: Use setup_fallback_model's defaults for ingestion
            # ingestion_llm_models=None # Example: Use general LLM passed to G4R, or setup_fallback_model defaults if that was None
        )

        graph = GraphForRAG(
            NEO4J_URI,
            NEO4J_USER,
            NEO4J_PASSWORD,
            embedder_client=openai_embedder,
            ingestion_config=ingestion_llm_config # Pass the new config
        )
        timings["graphforrag_init_total"] = (time.perf_counter() - graph_init_overall_start_time) * 1000
        logger.info(f"MAIN: GraphForRAG instance creation took {timings['graphforrag_init_total']:.2f} ms")
        
        run_data_setup = False 
        if run_data_setup:
            logger.info(f"Schema/Data setup started at: {get_current_time_ms()}")
            setup_overall_start_time = time.perf_counter()
            
            s_time = time.perf_counter(); await graph.clear_all_known_indexes_and_constraints(); timings["clear_indexes_constraints"] = (time.perf_counter() - s_time) * 1000
            s_time = time.perf_counter(); await graph.clear_all_data(); timings["clear_data"] = (time.perf_counter() - s_time) * 1000
            s_time = time.perf_counter(); await graph.ensure_indices(); timings["ensure_indices"] = (time.perf_counter() - s_time) * 1000
            
            timings["schema_data_setup_total"] = (time.perf_counter() - setup_overall_start_time) * 1000
            logger.info(f"Schema/Data setup finished. Duration: {timings['schema_data_setup_total']:.2f} ms")

            logger.info(f"Data ingestion started at: {get_current_time_ms()}")
            ingestion_overall_start_time = time.perf_counter()
            for i, source_set_info in enumerate(source_data_sets): # source_set_info is the whole block
                s_time = time.perf_counter()
                await graph.add_documents_from_source(
                    source_data_block=source_set_info # PASS THE ENTIRE DICTIONARY
                )
                # Calculate timing based on source_set_info['name'] if needed for logging key
                source_name_for_timing = source_set_info.get("name", f"unknown_source_{i+1}")
                timings[f"data_ingestion_source_{source_name_for_timing}"] = (time.perf_counter() - s_time) * 1000
            timings["data_ingestion_total"] = (time.perf_counter() - ingestion_overall_start_time) * 1000
            logger.info(f"Data ingestion finished. Duration: {timings['data_ingestion_total']:.2f} ms")
            logger.info("\n--- All document sets processed ---")
        else:
            logger.info("Skipping schema/data setup and ingestion as `run_data_setup` is False.")

        section_start_time = time.perf_counter()
        data_exists = False
        # try:
        #     if graph and graph.driver:
        #         query_result = await graph.driver.execute_query("MATCH (c:Chunk) RETURN count(c) > 0 AS chunks_exist", database_=graph.database)
        #         if query_result and query_result[0] and query_result[0][0]: 
        #             data_exists = query_result[0][0].get("chunks_exist", False)
        # except Exception as e_db_check:
        #     logger.error(f"Error checking for data existence: {e_db_check}", exc_info=True)

        # if not data_exists and not run_data_setup:
        #      logger.warning("No Chunk data found. Please run ingestion at least once (set run_data_setup=True).")
        #      # If no data and not running setup, we might want to return early or skip search
        #      # For now, it will proceed but search will likely find nothing.
        # timings["data_existence_check"] = (time.perf_counter() - section_start_time) * 1000
        data_exists = True

        # full_search_query = "What is Pooh favourite food?"
        # full_search_query = "What type of cover does Surface Pro have?"
        # full_search_query = "What is cheaper Surface Pro or Macbook air?"
        # full_search_query = "Apple MacBook Air (M3 Chip)"
        # full_search_query = "ASUS ROG Zephyrus G16 (2024 GU605)"
        full_search_query = "What is the cheapest laptop for power users?"
        
        timings["query_embedding_generation (explicit_in_main)"] = 0.0 
        logger.info(f"MAIN: Explicit query embedding generation in main is SKIPPED for this test.")
        
        logger.info(f"\n--- Setting up Comprehensive Search Test at: {get_current_time_ms()} ---")
        section_start_time = time.perf_counter()
        
        comprehensive_search_config = SearchConfig(
            chunk_config=ChunkSearchConfig(
                search_methods=[ChunkSearchMethod.KEYWORD, ChunkSearchMethod.SEMANTIC],
                limit=3, 
                min_results=2, 
                keyword_fetch_limit=10, 
                semantic_fetch_limit=10,
                min_similarity_score=0.7, 
                rrf_k=60
            ),
            entity_config=EntitySearchConfig(
                search_methods=[ 
                    EntitySearchMethod.KEYWORD_NAME, 
                    EntitySearchMethod.SEMANTIC_NAME, 
                ],
                limit=4, 
                min_results=1, 
                keyword_fetch_limit=15, 
                semantic_name_fetch_limit=15, 
                min_similarity_score_name=0.7,
                rrf_k=60
            ),
            relationship_config=RelationshipSearchConfig(
                search_methods=[RelationshipSearchMethod.KEYWORD_FACT, RelationshipSearchMethod.SEMANTIC_FACT],
                limit=3, 
                min_results=1, 
                keyword_fetch_limit=10, 
                semantic_fetch_limit=10,
                min_similarity_score=0.7,
                rrf_k=60
            ),
            mention_config=MentionSearchConfig( 
                search_methods=[MentionSearchMethod.KEYWORD_FACT, MentionSearchMethod.SEMANTIC_FACT],
                limit=3,
                min_results=1,
                keyword_fetch_limit=10,
                semantic_fetch_limit=10,
                min_similarity_score=0.65, 
                rrf_k=60
            ),
            source_config=SourceSearchConfig( 
                search_methods=[SourceSearchMethod.KEYWORD_CONTENT, SourceSearchMethod.SEMANTIC_CONTENT],
                limit=2, 
                min_results=1, 
                keyword_fetch_limit=5, 
                semantic_fetch_limit=5,
                min_similarity_score=0.7,
                rrf_k=60
            ),
            product_config=ProductSearchConfig( 
                search_methods=[
                    ProductSearchMethod.KEYWORD_NAME_CONTENT,
                    ProductSearchMethod.SEMANTIC_NAME,
                    ProductSearchMethod.SEMANTIC_CONTENT
                ],
                limit=5, 
                min_results=2, 
                keyword_fetch_limit=5,
                semantic_name_fetch_limit=5,
                semantic_content_fetch_limit=5,
                min_similarity_score_name=0.65, # Adjusted from 0.1
                min_similarity_score_content=0.7, # Adjusted from 0.1
                rrf_k=60
            ),
            mqr_config=MultiQueryConfig( 
                enabled=True, 
                include_original_query=True, # New field: Default is True, explicitly shown
                max_alternative_questions=3, # Generates up to 2 alternatives
                # mqr_llm_models=["gpt-4o-mini", "gemini-2.0-flash"]          # New field: None means use main service LLM for MQR
                # Example: Use specific models for MQR generation
                # mqr_llm_models=["gpt-4o-mini", "gemini-2.0-flash"] 
                # Example: Exclude original, only use alternatives (if any generated)
                # include_original_query=False,
                # max_alternative_questions=3 
            ),
            cypher_search_config=CypherSearchConfig( # ADDED Cypher Search Config
                enabled=True, 
                
                llm_models=["gpt-4o-mini", "gemini-2.0-flash"], # Optionally specify models for Cypher generation
                flagged_properties_config=FlaggedPropertiesConfig(
                        nodes={
                            "Product": {
                                "category": PropertyValueConfig(limit=10),
                                "target_audience_tags": PropertyValueConfig(limit=10)
                            },

                        },                    
                    ),
                custom_schema_string=CUSTOM_SHEMA_STRING
            ),
            overall_results_limit=15 
        )
        
        config_dump_str = comprehensive_search_config.model_dump_json(indent=2, exclude_none=True)
        timings["search_config_setup_log"] = (time.perf_counter() - section_start_time) * 1000
        logger.info(f"Using comprehensive search config (setup/log took {timings['search_config_setup_log']:.2f} ms): {config_dump_str}")


        section_start_time = time.perf_counter()
        if graph: 
            if data_exists or run_data_setup : 
                combined_results: CombinedSearchResults = await graph.search(
                    full_search_query, 
                    config=comprehensive_search_config
                )
                timings["comprehensive_search_call (graph.search)"] = (time.perf_counter() - section_start_time) * 1000
                logger.info(f"Comprehensive search call (graph.search) finished. Duration: {timings['comprehensive_search_call (graph.search)']:.2f} ms")

                if combined_results.items:
                    logger.info(f"Found {len(combined_results.items)} combined results for '{full_search_query}':")
                    for i, item in enumerate(combined_results.items):
                        logger.info(f"  --- Result {i+1} ({item.result_type}, Score: {item.score:.4f}) ---")
                        logger.info(f"    UUID: {item.uuid}")
                        if item.name: 
                            logger.info(f"    Name: {item.name}")
                        
                        # Content logging (for Chunk, Source, Product)
                        # Product.content is its textual description.
                        if item.content and item.result_type in ["Chunk", "Source", "Product"]:
                            logger.info(f"    Content Snippet: {item.content[:100]}...")
                        
                        # Fact sentence logging (for Relationship, Mention)
                        if item.fact_sentence and item.result_type in ["Relationship", "Mention"]:
                             logger.info(f"    Fact: {item.fact_sentence}")
                        
                        # Label logging (for Entity)
                        if item.label and item.result_type == "Entity":
                             logger.info(f"    Label: {item.label}")
                        
                        # Mention specific fields
                        if item.result_type == "Mention":
                            if item.source_node_uuid: # This is the Chunk UUID for MENTIONS
                                logger.info(f"    Mention Source (Chunk) UUID: {item.source_node_uuid}")
                            if item.target_node_uuid: # This is the Entity/Product UUID mentioned
                                logger.info(f"    Mention Target (Entity/Product) UUID: {item.target_node_uuid}")

                        # Connected Facts logging (for Entity and Product using the new unified structure)
                        if item.connected_facts and item.result_type in ["Entity", "Product"]:
                            logger.info(f"    Connected Facts ({len(item.connected_facts)}):")
                            for fact_idx, fact_data in enumerate(item.connected_facts):
                                if fact_data is None:
                                    logger.warning(f"      {fact_idx+1}. Encountered a null fact_data object in connected_facts. Skipping.")
                                    continue

                                log_display_parts = [f"      {fact_idx+1}."]
                                direction = fact_data.get('direction', 'UNKNOWN_DIRECTION')
                                rel_type_from_query = fact_data.get('relationship_type', 'UNKNOWN_REL_TYPE')
                                connected_node_name = fact_data.get('connected_node_name', 'Unknown Connected Node')
                                connected_node_labels = fact_data.get('connected_node_labels', [])
                                rel_props = fact_data.get('relationship_properties', {})

                                log_display_parts.append(f"[{direction}] --[{rel_type_from_query}]--> '{connected_node_name}' (Labels: {connected_node_labels})")
                                
                                fact_sentence_from_rel_props = None
                                if isinstance(rel_props, dict):
                                    fact_sentence_from_rel_props = rel_props.get('fact_sentence')
                                    
                                    # For RELATES_TO, relation_label is also in rel_props
                                    if rel_type_from_query == "RELATES_TO" and 'relation_label' in rel_props:
                                        log_display_parts.append(f"(Rel Label: {rel_props.get('relation_label', 'N/A')})")
                                
                                if fact_sentence_from_rel_props:
                                    log_display_parts.append(f": \"{fact_sentence_from_rel_props[:70]}...\"")
                                
                                # Optionally log other simple relationship properties if needed for debugging
                                # simple_props_to_log = {k: v for k, v in rel_props.items() if isinstance(v, (str, int, float, bool)) and k not in ['fact_sentence', 'fact_embedding', 'uuid', 'relation_label', 'created_at', 'last_seen_at', 'source_chunk_uuid']}
                                # if simple_props_to_log:
                                #     log_display_parts.append(f" RelProps: {simple_props_to_log}")
                                
                                logger.info(" ".join(log_display_parts))
                        
                        if item.metadata:
                            # Filter out metadata that is already explicitly logged or too verbose for this summary
                            metadata_to_log = item.metadata.copy()
                            keys_to_exclude_from_metadata_log = [
                                'uuid', 'name', 'content', 'description', 'label', 'score', 'result_type', 
                                'connected_facts', 'fact_sentence', 'source_node_uuid', 'target_node_uuid',
                                'contributing_methods', 'unnormalized_score', 'normalization_applied', 
                                'normalization_N_methods', 'normalization_max_score', 
                                'original_method_source_before_mqr_enhancement', 'inter_query_rrf_score',
                                # Type-specific keys already handled or part of main display
                                'source_description', 'chunk_number', # for Chunk
                                'sku', 'price', # for Product
                                'target_node_type' # for Mention
                            ]
                            # Also exclude any keys ending with _embedding
                            for key in list(metadata_to_log.keys()): # Iterate over a copy of keys for safe deletion
                                if key.endswith("_embedding") or key in keys_to_exclude_from_metadata_log:
                                    del metadata_to_log[key]
                            
                            if metadata_to_log: # Only log if there's anything left
                                logger.info(f"    Metadata: {metadata_to_log}")
                else:
                    logger.info(f"No combined results found for '{full_search_query}'.")
                if combined_results.context_snippet:
                    snippet_filename = "context_snippet_output.txt"
                    try:
                        with open(snippet_filename, "w", encoding="utf-8") as f:
                            f.write(combined_results.context_snippet)
                        logger.info(f"Context snippet saved to '{snippet_filename}'")
                    except IOError as e:
                        logger.error(f"Failed to write context snippet to file '{snippet_filename}': {e}")
                else:
                    logger.info("No context snippet generated to save.")   
                # Save source_data_snippet to file
                if combined_results.source_data_snippet:
                    source_snippet_filename = "source_references_snippet.txt"
                    try:
                        with open(source_snippet_filename, "w", encoding="utf-8") as f:
                            f.write(combined_results.source_data_snippet)
                        logger.info(f"Source data references snippet saved to '{source_snippet_filename}'")
                    except IOError as e:
                        logger.error(f"Failed to write source data references snippet to file '{source_snippet_filename}': {e}")
                else:
                    logger.info("No source data references snippet generated to save.")  

                # Log LLM-generated Cypher query and results if present
                if combined_results.executed_llm_cypher_query:
                    logger.info(f"\n--- LLM-Generated Cypher Query Executed ---")
                    logger.info(f"{combined_results.executed_llm_cypher_query}")
                    if combined_results.raw_llm_cypher_query_results:
                        logger.info(f"  --- Raw Results from LLM Cypher ({len(combined_results.raw_llm_cypher_query_results)} items) ---")
                        for i, cypher_res_item in enumerate(combined_results.raw_llm_cypher_query_results):
                            if i < 10: # Limit display for brevity
                                logger.info(f"    {i+1}. {cypher_res_item}")
                            elif i == 10:
                                logger.info(f"    ... (and {len(combined_results.raw_llm_cypher_query_results) - 10} more items)")
                                break
                    else:
                        logger.info("  --- No raw results returned from the executed LLM Cypher query. ---")
                elif comprehensive_search_config.cypher_search_config and comprehensive_search_config.cypher_search_config.enabled:
                    logger.info("\n--- LLM-Generated Cypher Search was enabled, but no query was generated or executed. ---")


            else:
                logger.warning("Skipping search call as no data exists and data setup was not run.")
                timings["comprehensive_search_call (graph.search)"] = 0.0
        else:
            logger.error("Graph object not initialized, skipping comprehensive search call.")
            timings["comprehensive_search_call (graph.search)"] = 0.0
        
        
        logger.info(f"--- Comprehensive Search Test Complete at: {get_current_time_ms()} ---")
        
        
        usage_log_start_time = time.perf_counter()
        if graph: 
            
            total_gen_usage = graph.get_total_generative_llm_usage()
            if total_gen_usage and total_gen_usage.has_values():
                gen_details = (f"Requests: {total_gen_usage.requests}, "
                               f"Request Tokens: {total_gen_usage.request_tokens or 0}, "
                               f"Response Tokens: {total_gen_usage.response_tokens or 0}, "
                               f"Total Tokens: {total_gen_usage.total_tokens or 0}")
                logger.info(f"[bold blue]Total Generative LLM Usage:[/bold blue] {gen_details}")
            else:
                logger.info("[bold blue]Total Generative LLM Usage:[/bold blue] No generative usage data reported.")

            
            total_embed_usage = graph.get_total_embedding_usage()
            if total_embed_usage and total_embed_usage.has_values():
                embed_details = (f"Requests: {total_embed_usage.requests}, "
                                 f"Request Tokens: {total_embed_usage.request_tokens or 0}, " 
                                 f"Total Tokens: {total_embed_usage.total_tokens or 0}")
                logger.info(f"[bold green]Total Embedding Usage:[/bold green] {embed_details}")
            else:
                logger.info("[bold green]Total Embedding Usage:[/bold green] No embedding usage data reported.")
            
            overall_usage = graph.get_total_llm_usage() 
            if overall_usage and overall_usage.has_values():
                overall_details = (f"Requests: {overall_usage.requests}, "
                                   f"Request Tokens: {overall_usage.request_tokens or 0}, "
                                   f"Response Tokens: {overall_usage.response_tokens or 0}, "
                                   f"Total Tokens: {overall_usage.total_tokens or 0}")
                logger.info(f"[bold magenta]Overall Combined LLM & Embedding Usage:[/bold magenta] {overall_details}")
            elif not (total_gen_usage.has_values() or total_embed_usage.has_values()): 
                logger.info("[bold magenta]Overall Combined LLM & Embedding Usage:[/bold magenta] No usage data reported.")
        else:
            logger.info("[bold magenta]Overall LLM Usage:[/bold magenta] Graph object not initialized.")
        timings["get_llm_usage"] = (time.perf_counter() - usage_log_start_time) * 1000
        

    except Exception as e:
        logger.error(f"An error occurred in main execution: {e}", exc_info=True)
    finally:
        if graph:
            section_start_time = time.perf_counter()
            await graph.close()
            timings["graph_close"] = (time.perf_counter() - section_start_time) * 1000
        
        main_end_time = time.perf_counter()
        timings["total_main_execution"] = (main_end_time - main_start_time) * 1000
        
        logger.info(f"\n[bold cyan]--- TIMING SUMMARY (ms) ---[/bold cyan]")
        sum_of_parts = sum(v for k, v in timings.items() if k != "total_main_execution")
        
        total_main_execution_for_percentage = timings.get("total_main_execution", 1)
        if total_main_execution_for_percentage == 0:
            total_main_execution_for_percentage = 1 

        for operation, duration in timings.items():
            if operation == "total_main_execution": continue
            percentage = (duration / total_main_execution_for_percentage) * 100 
            logger.info(f"{operation:<45}: {duration:>10.2f} ms ({percentage:>6.2f}%)")
        
        unaccounted_time = timings.get("total_main_execution", 0) - sum_of_parts
        if abs(unaccounted_time) > 1.0 : 
             percentage_unaccounted = (unaccounted_time / total_main_execution_for_percentage) * 100 
             logger.info(f"{'Unaccounted time':<45}: {unaccounted_time:>10.2f} ms ({percentage_unaccounted:>6.2f}%)")
        
        calculated_total_main_execution = sum_of_parts + (unaccounted_time if abs(unaccounted_time) > 1.0 else 0)
        calculated_total_percentage = (calculated_total_main_execution / total_main_execution_for_percentage) * 100
        logger.info(f"{'Total Main Execution (Calculated)':<45}: {calculated_total_main_execution:>10.2f} ms ({calculated_total_percentage:>6.2f}%)")
        logger.info(f"{'Total Main Execution (Actual)':<45}: {timings.get('total_main_execution', 0):>10.2f} ms (100.00%)")
        logger.info(f"[bold cyan]Main execution finished at: {get_current_time_ms()}. Total duration: {timings.get('total_main_execution',0):.2f} ms[/bold cyan]")

if __name__ == "__main__":
    asyncio.run(main())