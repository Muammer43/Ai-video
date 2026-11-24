from pydantic import BaseModel, Field
from typing import Literal

class CreateJob(BaseModel):
    topic: str = Field(min_length=3, max_length=240)
    category: str = Field(default="general", max_length=60)
    style: str = Field(default="cinematic", max_length=60)
    duration: int = Field(default=30, ge=15, le=90)
    platforms: list[Literal["youtube", "tiktok", "instagram"]] = ["youtube", "tiktok", "instagram"]

class AppSettings(BaseModel):
    auto_publish: bool = False
    quality_threshold: int = Field(default=80, ge=50, le=100)
