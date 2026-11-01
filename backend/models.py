from typing import Literal

from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    mode: Literal["local", "gemini"] = "local"


class ReviewRequest(BaseModel):
    decision: Literal["confirmed", "dismissed", "resolved"]
    note: str = Field(default="", max_length=2000)
