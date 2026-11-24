from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class GroundedStatement(BaseModel):
    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class TimelineEvent(BaseModel):
    timestamp: datetime | None = None
    description: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class InvestigationOutput(BaseModel):
    status: str
    confirmed_facts: list[GroundedStatement] = Field(default_factory=list)
    inferred_relationships: list[GroundedStatement] = Field(default_factory=list)
    model_interpretations: list[GroundedStatement] = Field(default_factory=list)
    recommendations: list[GroundedStatement] = Field(default_factory=list)
    intelligence_gaps: list[str] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    campaign_explanation: list[GroundedStatement] = Field(default_factory=list)
    relationship_explanation: list[GroundedStatement] = Field(default_factory=list)
    actor_analysis: list[GroundedStatement] = Field(default_factory=list)
    malware_analysis: list[GroundedStatement] = Field(default_factory=list)
    vulnerability_analysis: list[GroundedStatement] = Field(default_factory=list)
    attack_technique_analysis: list[GroundedStatement] = Field(default_factory=list)
    sector_analysis: list[GroundedStatement] = Field(default_factory=list)
