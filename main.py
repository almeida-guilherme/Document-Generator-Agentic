from dotenv import load_dotenv
from create_video import create_frames, caption_frame
from langchain_openai import ChatOpenAI
from schemas import FrameCaption, format_timestamp
from transcribe import transcribe_audio
from structure import structure_pdd
from render import render_docx

load_dotenv()

video_path = "cache/test2.mp4"

# Getting the frames from the video
frames = create_frames(video_path)
llm = ChatOpenAI(model="gpt-4o-mini").with_structured_output(FrameCaption)
captions = [caption_frame(frame, llm) for frame in frames]

for c in captions:
    print(f"[{c['timestamp']:.1f}s] {c['screen_or_system']}")
    print(f"  Action: {c['observed_action']}")
    print(f"  Text: {c['visible_text']}")
    print()

for c in captions:
    c["time"] = format_timestamp(c["timestamp"])

# Getting the audio from the video
transcript = transcribe_audio(video_path)
print(f"\nTranscript segments: {len(transcript)}")
for t in transcript:
    print(f"  [{t['start']:.1f}s] {t['text']}")

# Creating PDD Structure
pdd = structure_pdd(captions, transcript)

print(f"Process: {pdd.process_name}")
print(f"Project Proposal: {pdd.project_proposal}")
print("\nSteps:")
for step in pdd.as_is:
    print(f"  {step.number}. [{step.time}] {step.action} ({step.system})")
    print(f"     Result: {step.result}")
    print(f"     Frame: {step.frame_ref}")
print(f"\nBusiness Exceptions: {pdd.business_exceptions}")
print(f"System Exceptions: {pdd.system_exceptions}")

# Creating final document
output_path = render_docx(pdd)
print(f"\nDocument generated: {output_path}")