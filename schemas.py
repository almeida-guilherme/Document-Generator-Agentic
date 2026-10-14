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

class ProcessOverview(BaseModel):
    process_name: str = Field(description="Short, descriptive name of the documented process")
    project_proposal: str = Field(description="Summary of the project and its current (as-is) state, for the Introduction section")
    goal: str = Field(description="One sentence stating the outcome the process achieves; used to decide which screens belong to the process")


class DraftStep(BaseModel):
    instruction: str = Field(description="Automation instruction describing what needs to be done in this step, written as a directive (e.g. 'You need to enter the OLX website', 'You need to search for \"Nintendo Switch\" in the search bar')")
    short_label: str = Field(description="A very short label (max 4-5 words) summarizing this step's action, suitable for a flowchart node")
    frame_ids: list[str] = Field(description="IDs of the observations (e.g. 'F012') that evidence this step, in chronological order; the first one is used as the step's main screenshot")


class WindowResult(BaseModel):
    steps: list[DraftStep] = Field(default_factory=list, description="Process steps found in this part of the recording, in chronological order")
    business_exceptions: list[ExceptionItem] = Field(default_factory=list, description="Business-related exceptions identified in this part, if any")
    system_exceptions: list[ExceptionItem] = Field(default_factory=list, description="System/application-related exceptions identified in this part, if any")


# --- The assembled document (numbers, times and image paths are filled in by code, not by the LLM) ---

class Step(BaseModel):
    number: int
    time: str
    instruction: str
    short_label: str
    frame_ids: list[str]
    frame_paths: list[str] = Field(default_factory=list)


class PDD(BaseModel):
    process_name: str
    project_proposal: str
    as_is: list[Step]
    business_exceptions: list[ExceptionItem] = Field(default_factory=list)
    system_exceptions: list[ExceptionItem] = Field(default_factory=list)


def format_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = int(seconds % 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
