"""First sponsor check: direct Strands tool calling, then supported-model fallback.
Run: .venv/bin/python -m scripts.check_inference
Never prints endpoint credentials or raw responses.
"""
import json
import os
import sys
from dotenv import load_dotenv
load_dotenv(".env.local")
load_dotenv()
from strands import Agent, tool
from backend.agent import akamai_configured, akamai_model, call_akamai

def main():
    if not akamai_configured():
        print(json.dumps({"status":"blocked","missing":[k for k in ["AKAMAI_BASE_URL","AKAMAI_API_KEY","AKAMAI_MODEL"] if not os.getenv(k)],"message":"Sponsor credentials are required; no inference was attempted."}))
        return 2
    called = []
    @tool
    def integration_probe(value: str) -> str:
        """Echo a value to verify Strands function tool calling."""
        called.append(value)
        return value
    try:
        agent = Agent(model=akamai_model(), tools=[integration_probe], callback_handler=None, system_prompt="Call integration_probe with value dealfeed-ready exactly once, then finish.")
        agent("Verify the integration.")
        if not called:
            raise RuntimeError("No tool call")
        print(json.dumps({"direct":"passed","strandsToolCalls":len(called)}))
        selected = "direct"
    except Exception as exc:
        print(json.dumps({"direct":"failed","errorType":type(exc).__name__,"next":"Test Akamai generation as a tool with Bedrock orchestration."}))
        if not os.getenv("BEDROCK_MODEL_ID"):
            print(json.dumps({"status":"blocked","missing":["BEDROCK_MODEL_ID"],"message":"Fallback requires AWS credentials and an enabled Bedrock model."}))
            return 2
        selected = "tool"
    # Exercise the real retrieval → Akamai tool → validated brief path in the selected mode.
    from backend.agent import generate_draft
    from backend.store import Store
    from datetime import date, timedelta
    from tempfile import TemporaryDirectory
    os.environ["STRANDS_MODEL_MODE"] = selected
    os.environ["AI_MODE"] = "live"
    try:
        with TemporaryDirectory() as tmp:
            brief, trace, mode = generate_draft(Store(tmp+"/probe.sqlite"), {"projectId":"olive-table","name":"Sample Restaurant","email":"demo@example.com","budget":"$3,000–$5,000","location":"Austin, TX","deadline":str(date.today()+timedelta(days=60)),"requirements":"A five-page restaurant website with seasonal menus, our story, and a link to our existing reservation platform. We will provide copy and photography."})
        print(json.dumps({"status":"passed","mode":mode,"STRANDS_MODEL_MODE":selected,"tools":[t["tool"] for t in trace],"clarifications":len(brief["questions"])}))
        return 0
    except Exception as exc:
        print(json.dumps({"status":"failed","stage":"grounded_brief","errorType":type(exc).__name__}))
        return 1

if __name__ == "__main__":
    sys.exit(main())
