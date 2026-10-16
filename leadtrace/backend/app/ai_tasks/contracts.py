from typing import Literal
from uuid import UUID
from pydantic import BaseModel,ConfigDict,Field,model_validator

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')
class ReviewOptions(Strict):
    preset_id:str=Field(min_length=1,max_length=64)
    reasoning_effort:str=Field(min_length=1,max_length=32)
class StartTask(ReviewOptions):
    action:Literal['prefill','review','repair','revise']
    expected_workspace_id:UUID|None=None
    expected_task_version:int|None=Field(default=None,ge=1)
    expected_workspace_version:int|None=Field(default=None,ge=1)
    timeout_seconds:int=Field(default=1800,ge=60,le=7200)
    idempotency_key:UUID
    auto_review:ReviewOptions|None=None
    instructions:str|None=Field(default=None,max_length=12000)

    @model_validator(mode='after')
    def revision_instructions(self):
        if self.action=='revise':
            if not self.instructions or not self.instructions.strip():
                raise ValueError('Revision instructions are required')
            self.instructions=self.instructions.strip()
            if self.auto_review is not None:
                raise ValueError('Directed revision does not start independent review')
        elif self.instructions is not None:
            raise ValueError('Instructions are only supported for directed revision')
        return self
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
