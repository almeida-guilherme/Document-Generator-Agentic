from dotenv import load_dotenv
from create_video import create_frames, caption_frame
from langchain_openai import ChatOpenAI
from schemas import FrameCaption

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
