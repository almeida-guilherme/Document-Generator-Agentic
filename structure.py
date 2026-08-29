import json
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_community.callbacks import get_openai_callback
from schemas import PDD
from prompts.structure_prompt import STRUCTURE_SYSTEM_PROMPT


def structure_pdd(captions: list[dict]) -> PDD:
    llm = ChatOpenAI(model="gpt-4o-mini", max_retries=5).with_structured_output(PDD)

    observations_text = json.dumps(captions, ensure_ascii=False, indent=2)

    messages = [
        SystemMessage(content=STRUCTURE_SYSTEM_PROMPT),
        HumanMessage(content=f"Observations extracted from the video:\n\n{observations_text}"),
    ]

    with get_openai_callback() as cb:
        result: PDD = llm.invoke(messages)
        print(f"\n--- Token usage (structure_pdd) ---")
        print(f"Total tokens: {cb.total_tokens} | Cost: ${cb.total_cost:.4f}")
        print("------------------------------------\n")

    return result