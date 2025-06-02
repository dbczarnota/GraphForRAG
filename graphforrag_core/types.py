# graphforrag_core/types.py
from pydantic import BaseModel

class ResolvedEntityInfo(BaseModel):
    uuid: str
    name: str 
    label: str