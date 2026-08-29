from dotenv import load_dotenv
from create_video import create_frames, caption_frame
from langchain_openai import ChatOpenAI
from schemas import FrameCaption,format_timestamp

load_dotenv()

#Isso aqui vai ser um grafo
frames = create_frames("test1.mp4")
llm = ChatOpenAI(model="gpt-4o-mini").with_structured_output(FrameCaption)
captions = [caption_frame(frame, llm) for frame in frames]

for c in captions:
    print(f"[{c['timestamp']:.1f}s] {c['screen_or_system']}")
    print(f"  Action: {c['observed_action']}")
    print(f"  Text: {c['visible_text']}")
    print()

for c in captions:
    c["time"] = format_timestamp(c["timestamp"])

from structure import structure_pdd

pdd = structure_pdd(captions)

print(f"Process: {pdd.process_name}")
print(f"Objective: {pdd.objective}")
print(f"Scope: {pdd.scope_start} → {pdd.scope_end}")
print(f"Tools: {pdd.tools}")
print("\nSteps:")
for step in pdd.as_is:
    print(f"  {step.number}. [{step.time}] {step.action} ({step.system})")
    print(f"     Result: {step.result}")
print(f"\nBusiness rules: {pdd.business_rules}")
print(f"Exceptions: {pdd.exceptions}")

for step in pdd.as_is:
    print(f"  {step.number}. [{step.time}] {step.action} ({step.system})")
    print(f"     Result: {step.result}")
    print(f"     Frame: {step.frame_ref}")

from render import render_docx

output_path = render_docx(pdd)
print(f"\nDocument generated: {output_path}")