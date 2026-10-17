"""Typed response schemas; the frontend contract is independent of SQLite table layout."""
from typing import Optional

from pydantic import BaseModel


class ProjectOut(BaseModel):
    project_name: str


class BusinessProcessOut(BaseModel):
    business_process_id: Optional[str] = None
    business_process_name: Optional[str] = None


class TargetObjectOut(BaseModel):
    object_id: str
    object_name: str
    source_project: Optional[str] = None
    business_processes: list[BusinessProcessOut]
    column_count: int


class TargetColumnOut(BaseModel):
    column_id: str
    column_name: str
    step_count: int


class ChoiceOut(BaseModel):
    step_id: str
    relation_id: str
    relation_type: str
    source_object_id: str
    source_column_id: str
    source_object_name: str
    source_column_name: str
    target_object_id: str
    target_column_id: str
    target_object_name: str
    target_column_name: str
    component_id: Optional[str] = None
    component_name: Optional[str] = None
    component_type: Optional[str] = None
    business_process_id: Optional[str] = None
    business_process_name: Optional[str] = None
    confidence_class: Optional[str] = None
    confidence_reason_code: Optional[str] = None
    traversal_path: Optional[str] = None
    driving_expression: Optional[str] = None
    result_expression: Optional[str] = None
    expression_id: Optional[str] = None
    lineage_level: int
    is_terminal: bool
    has_more_upstream: bool
    upstream_choice_count: int


class UpstreamOut(BaseModel):
    choices: list[ChoiceOut]


class TerminalSourceOut(BaseModel):
    terminal_id: str
    object_id: str
    column_id: str
    object_name: str
    column_name: str
    object_type: Optional[str] = None
    leaf_relation_types: list[str]


class UltimateSourcesOut(BaseModel):
    project: str
    object_id: str
    column_id: str
    step_id: Optional[str] = None
    terminal_sources: list[TerminalSourceOut]


class RemainingDepthOut(BaseModel):
    step_id: str
    is_terminal: bool
    remaining_hops_exact: Optional[int] = None
    remaining_hops_min: int
    remaining_hops_max: int


class EndpointOut(BaseModel):
    object_id: Optional[str] = None
    object_name: Optional[str] = None
    object_type: Optional[str] = None
    column_id: Optional[str] = None
    column_name: Optional[str] = None


class ComponentOut(BaseModel):
    component_id: Optional[str] = None
    component_name: Optional[str] = None
    component_type: Optional[str] = None


class ConfidenceOut(BaseModel):
    confidence_class: Optional[str] = None
    reason_code: Optional[str] = None
    reason: Optional[str] = None


class DependencyOut(BaseModel):
    operand_order: Optional[int] = None
    object_id: Optional[str] = None
    column_id: Optional[str] = None
    object_name: Optional[str] = None
    object_type: Optional[str] = None
    column_name: Optional[str] = None


class PersistenceOut(BaseModel):
    status: str
    reason_code: Optional[str] = None
    reason: Optional[str] = None


class RelationDetailOut(BaseModel):
    relation_id: str
    relation_type: str
    source: EndpointOut
    target: EndpointOut
    component: ComponentOut
    business_process: BusinessProcessOut
    confidence: ConfidenceOut
    traversal_path: Optional[str] = None
    expression_id: Optional[str] = None
    driving_expression: Optional[str] = None
    result_expression: Optional[str] = None
    dependencies: list[DependencyOut]
    persistence: Optional[PersistenceOut] = None
    step_ids: list[str]


class StepDetailOut(RelationDetailOut):
    step_id: str
    path_id: str
    lineage_level: int
    hop_count: Optional[int] = None


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorOut(BaseModel):
    error: ErrorBody
