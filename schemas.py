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


class Step(BaseModel):
    number: int
    time: str
    action: str
    system: str
    result: str
    frame_ref: str
    short_label: str = Field(description="A very short label (max 4-5 words) summarizing this step's action, suitable for a flowchart node — e.g. 'Search YouTube', 'Open video', 'Configure OBS'")

class PDD(BaseModel):
    process_name: str = Field(description="Short, descriptive name of the documented process")
    project_proposal: str = Field(description="Summary of the project and its current (as-is) state, for the Introduction section")
    as_is: list[Step] = Field(description="Sequence of process steps, in chronological order")
    business_exceptions: list[ExceptionItem] = Field(default_factory=list, description="Business-related exceptions identified, if any")
    system_exceptions: list[ExceptionItem] = Field(default_factory=list, description="System/application-related exceptions identified, if any")


def format_timestamp(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"