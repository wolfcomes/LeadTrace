from typing import Literal
from uuid import UUID
from pydantic import BaseModel,ConfigDict,Field

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')
class ReviewOptions(Strict):
    preset_id:str=Field(min_length=1,max_length=64)
    reasoning_effort:str=Field(min_length=1,max_length=32)
class StartTask(ReviewOptions):
    action:Literal['prefill','review','repair']
    expected_workspace_id:UUID|None=None
    expected_task_version:int|None=Field(default=None,ge=1)
    expected_workspace_version:int|None=Field(default=None,ge=1)
    timeout_seconds:int=Field(default=1800,ge=60,le=7200)
    idempotency_key:UUID
    auto_review:ReviewOptions|None=None
class RetryTask(Strict):
    idempotency_key:UUID
class RepairRequest(ReviewOptions):
    timeout_seconds:int=Field(default=1800,ge=60,le=7200)
    idempotency_key:UUID
class AcceptRepair(Strict):
    proposal_sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
class LimitUpdate(Strict):
    max_concurrent:int=Field(ge=1,le=16)
class ModelPreset(ReviewOptions):
    label:str=Field(min_length=1,max_length=100)
    adapter:Literal['dsh','codex']
    model:str=Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$')
    efforts:list[str]=Field(min_length=1)
