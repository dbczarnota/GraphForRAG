# graphforrag_core/utils.py
import json
from datetime import datetime, date
import logging

logger = logging.getLogger("graph_for_rag.utils") # Specific logger for utils

def preprocess_metadata_for_neo4j(metadata: dict | None) -> dict:
    if not metadata:
        return {}
    processed_props = {}
    for key, value in metadata.items():
        if isinstance(value, dict):
            processed_props[key] = json.dumps(value)
        elif isinstance(value, (datetime, date)):
            processed_props[key] = value.isoformat()
        elif isinstance(value, list):
            new_list = []
            for item in value:
                if isinstance(item, dict):
                    new_list.append(json.dumps(item))
                elif isinstance(item, (datetime, date)):
                    new_list.append(item.isoformat())
                elif isinstance(item, (str, int, float, bool)) or item is None:
                    new_list.append(item)
                else:
                    logger.warning(f"Item of type {type(item)} in list for key '{key}' converted to string.")
                    new_list.append(str(item))
            processed_props[key] = new_list
        elif isinstance(value, (str, int, float, bool)) or value is None:
            processed_props[key] = value
        else:
            logger.warning(f"Metadata field '{key}' with type {type(value)} converted to string.")
            processed_props[key] = str(value)
    return processed_props

def normalize_entity_name(name: str) -> str:
    """
    Applies basic normalization to an entity name.
    - Converts to lowercase
    - Strips leading/trailing whitespace
    - Can be extended with more rules (e.g., punctuation removal, sorting words)
    """
    if not name:
        return ""
    normalized = name.lower().strip()
    # Example of removing some punctuation (can be expanded)
    # normalized = re.sub(r"[.,;:!?'\"()]", "", normalized)
    # Example of replacing multiple spaces with a single space
    # normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized
