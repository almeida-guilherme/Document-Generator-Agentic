from dotenv import load_dotenv
from pipeline import run_pdd_pipeline

load_dotenv()

output = run_pdd_pipeline("cache/test2.mp4", job_dir="cache/")
print(f"Document generated: {output}")