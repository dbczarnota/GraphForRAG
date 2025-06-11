CUSTOM_SHEMA_STRING = """
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
category: STRING {possible values: {2-in-1 Convertible, Gaming Laptop, Ultrabook Laptop}}
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
target_audience_tags: LIST {possible values: {Content Creators, Creatives, Executives, Gamers, General Users, Mobile Professionals, Power Users, Professionals, Students}}
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