import json
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_community.callbacks import get_openai_callback
from schemas import PDD
from prompts.structure_prompt import STRUCTURE_SYSTEM_PROMPT
from typing import cast


def structure_pdd(captions: list[dict], transcript: list[dict] | None = None) -> PDD:
    llm = ChatOpenAI(model="gpt-4o-mini", max_retries=5).with_structured_output(PDD)

    observations_text = json.dumps(captions, ensure_ascii=False, indent=2)

    if transcript:
        transcript_text = "\n".join(f"[{t['start']:.1f}s] {t['text']}" for t in transcript)
    else:
        transcript_text = "(no narration detected)"

    messages = [
        SystemMessage(content=STRUCTURE_SYSTEM_PROMPT),
        HumanMessage(content=f"Visual observations:\n\n{observations_text}\n\nAudio narration:\n\n{transcript_text}"),
    ]

    with get_openai_callback() as cb:
        result = cast(PDD, llm.invoke(messages))
        print(f"\n--- Token usage (structure_pdd) ---")
        print(f"Total tokens: {cb.total_tokens} | Cost: ${cb.total_cost:.4f}")
        print("------------------------------------\n")

    return result