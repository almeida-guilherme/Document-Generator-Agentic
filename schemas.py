from typing import Literal
from pydantic import BaseModel, Field


class FrameCaption(BaseModel):
    screen_or_system: str = Field(description="Which screen, application, or website is visible in the frame")
    observed_action: str = Field(description="What the user appears to be doing, or what is being displayed at this moment")
    visible_text: list[str] = Field(default_factory=list, description="Relevant text visible on screen (titles, fields, buttons, messages)")


class ExceptionItem(BaseModel):
    name: str = Field(description="Short name identifying the exception")
    action: str = Field(description="What action or condition triggers this exception")
    parameters: str = Field(default="", description="Relevant parameters or context for this exception, if any")
    action_to_be_taken: str = Field(description="What should be done when this exception occurs")


# --- What the LLM returns ---

class RequirementItem(BaseModel):
    category: Literal["frequency", "volume", "business_rule", "reference_data", "access", "other"] = Field(
        description="frequency: how often the process runs; volume: how many items per run; business_rule: logic or "
                    "lookups applied to the data; reference_data: tables or templates the process depends on; "
                    "access: systems, sites or permissions needed; other: anything else an automation developer must know")
    description: str = Field(description="The requirement as stated or shown, in one or two sentences")


class OutlineStep(BaseModel):
    instruction: str = Field(description="Automation instruction describing what needs to be done in this step, written as a directive (e.g. 'You need to enter the OLX website', 'You need to search for \"Nintendo Switch\" in the search bar')")
    short_label: str = Field(description="A very short label (max 4-5 words) summarizing this step's action, suitable for a flowchart node")
    frame_ids: list[str] = Field(description="IDs of the observations (e.g. 'F012') that evidence this step, in chronological order")
    narrated_at: float | None = Field(default=None, description="Timestamp in seconds of the narration segment that describes this step, or null if it isn't narrated")


class ProcessOutline(BaseModel):
    process_name: str = Field(description="Short, descriptive name of the documented process")
    project_proposal: str = Field(description="Summary of the project and its current (as-is) state, for the Introduction section")
    steps: list[OutlineStep] = Field(description="Every step of the process, once each, in the order they are performed")
    requirements: list[RequirementItem] = Field(default_factory=list, description="Business rules and requirements stated or shown, if any")
    business_exceptions: list[ExceptionItem] = Field(default_factory=list, description="Business-related exceptions identified, if any")
    system_exceptions: list[ExceptionItem] = Field(default_factory=list, description="System/application-related exceptions identified, if any")


class RefinedStep(BaseModel):
    number: int = Field(description="Number of the outline step being refined, exactly as given")
    instruction: str = Field(description="The step's instruction, made more specific with names, fields, buttons or values visible in its observations; same directive style")
    frame_ids: list[str] = Field(description="IDs of the observations that evidence this step, in chronological order")
    main_frame_id: str = Field(description="The one id from frame_ids used as the step's screenshot: the frame that best shows the step done (e.g. the completed form, not the empty one)")


class WindowRefinement(BaseModel):
    steps: list[RefinedStep] = Field(default_factory=list, description="One entry per outline step given, in the same order")


# --- The assembled document (numbers, times and image paths are filled in by code, not by the LLM) ---

class Step(BaseModel):
    number: int
    time: str
    instruction: str
    short_label: str
    frame_ids: list[str]
    main_frame_path: str | None = None


class PDD(BaseModel):
    process_name: str
    project_proposal: str
    as_is: list[Step]
    requirements: list[RequirementItem] = Field(default_factory=list)
    business_exceptions: list[ExceptionItem] = Field(default_factory=list)
    system_exceptions: list[ExceptionItem] = Field(default_factory=list)


def format_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = int(seconds % 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
