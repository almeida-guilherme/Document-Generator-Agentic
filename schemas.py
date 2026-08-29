from pydantic import BaseModel, Field

class FrameCaption(BaseModel):
    screen_or_system: str = Field(description="Which screen, application, or website is visible in the frame")
    observed_action: str = Field(description="What the user appears to be doing, or what is being displayed at this moment")
    visible_text: list[str] = Field(default_factory=list, description="Relevant text visible on screen (titles, fields, buttons, messages)")


class Step(BaseModel):
    number: int = Field(description="Sequential step number, starting at 1")
    time: str = Field(description="Approximate timestamp of the step, in mm:ss format")
    action: str = Field(description="Clear, objective description of the action performed in this step")
    system: str = Field(description="System, application, or screen where the action occurs")
    result: str = Field(description="What happens as a consequence of this action")
    frame_ref: str = Field(description="File path of the image evidencing this step")


class PDD(BaseModel):
    process_name: str = Field(description="Short, descriptive name of the documented process")
    objective: str = Field(description="Objective of the process, in 1-2 sentences")
    scope_start: str = Field(description="Where the process begins (observed initial state)")
    scope_end: str = Field(description="Where the process ends (observed final state)")
    tools: list[str] = Field(description="List of systems/tools used throughout the process")
    as_is: list[Step] = Field(description="Sequence of process steps, in chronological order")
    business_rules: list[str] = Field(default_factory=list, description="Identified business rules, if any")
    exceptions: list[str] = Field(default_factory=list, description="Observed exceptions or deviations, if any")

def format_timestamp(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"