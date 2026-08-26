CAPTION_PROMPT = """You are analyzing a single frame extracted from a screen recording of a business process.

Describe objectively:
1. Which screen, application, or website is visible. Identify it only from clear, unambiguous evidence (e.g. a visible title bar, logo, or URL) — do not guess an application based on icon shape or color alone.
2. What action the user appears to be performing, or what is being displayed at this moment.
3. Any clearly legible text on screen (titles, fields, buttons, messages). Only transcribe text you can read with confidence — if text is too small, blurry, or ambiguous to read reliably, omit it rather than guessing.

Be factual and concise. Do not infer or fabricate information that is not visibly present in the image. If something is unclear or uncertain, state that explicitly instead of assuming."""