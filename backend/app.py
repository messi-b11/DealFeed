import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
from fastapi import FastAPI, Request, Depends, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum
from pydantic import BaseModel, Field
from .models import BuyerInput, Approval, ProposalInput, ProjectInput, MatchInput, DealApproval, SelectionInput
from .store import Store, Conflict, CATALOG
from .agent import generate_draft, save_approved_request, InferenceUnavailable, akamai_configured

app = FastAPI(title="DealFeed API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[os.getenv("ALLOWED_ORIGIN", "http://127.0.0.1:3000")], allow_methods=["GET", "POST"], allow_headers=["Authorization", "X-DealFeed-Authorization", "Content-Type"])
store = Store()
session_secret = os.getenv("SESSION_SECRET") or (secrets.token_hex(32) if not os.getenv("AWS_LAMBDA_FUNCTION_NAME") else "")

class APIError(Exception):
    def __init__(self, status, code, message, fields=None):
        self.status, self.code, self.message, self.fields = status, code, message, fields or {}

@app.exception_handler(APIError)
async def api_error(request, exc):
    return JSONResponse(status_code=exc.status, content={"error":{"code":exc.code,"message":exc.message,"fields":exc.fields}})

@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    fields = {str(e["loc"][-1]):e["msg"] for e in exc.errors()}
    return JSONResponse(status_code=422, content={"error":{"code":"clarification_required","message":"A few details need your attention.","fields":fields}})

@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    return JSONResponse(status_code=500, content={"error":{"code":"server_error","message":"Something went wrong. Please retry; no automatic submission was made.","fields":{}}})

def now():
    return datetime.now(timezone.utc).isoformat()

def actor(request: Request):
    try:
        # Keep app identity separate from an optional HTTPS preview Basic-auth
        # gate. Legacy API clients can continue using standard Authorization.
        token = request.headers.get("X-DealFeed-Authorization", request.headers.get("Authorization", "")).removeprefix("Bearer ")
        payload, signature = token.split(".")
        expected = hmac.new(session_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not session_secret or not hmac.compare_digest(signature, expected):
            raise ValueError()
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if data["exp"] < time.time():
            raise ValueError()
        return data
    except Exception:
        raise APIError(401, "session_expired", "Your demo session expired. Retry to start a new session.")

def require_role(user, role):
    if user["role"] != role:
        raise APIError(403, "forbidden", "This action is not available to this account.")

def get_owned_request(id, user):
    record = store.get("request", id)
    key = "buyerId" if user["role"] == "buyer" else "businessId"
    if not record or record[key] != user["id"]:
        raise APIError(404, "not_found", "Request not found.")
    return record

def expose_project(project):
    result = dict(project)
    if result["image"].startswith("projects/") and os.getenv("BUCKET_NAME"):
        import boto3
        result["image"] = boto3.client("s3").generate_presigned_url("get_object", Params={"Bucket":os.environ["BUCKET_NAME"],"Key":result["image"]}, ExpiresIn=3600)
    return result

@app.get("/health")
def health():
    return {"status":"ok", "mode":os.getenv("AI_MODE", "live"), "storage":"dynamodb" if store.table_name else "sqlite", "akamaiConfigured":akamai_configured(), "strandsMode":os.getenv("STRANDS_MODEL_MODE", "direct"), "asyncAnalysis":async_analysis_enabled()}

class SessionInput(BaseModel):
    role: str = Field(pattern="^(buyer|provider)$")
    businessId: str | None = None
    buyerId: str | None = Field(default=None, pattern=r"^buyer-[a-zA-Z0-9-]{8,80}$")

@app.post("/sessions")
def session(data: SessionInput):
    if os.getenv("DEMO_AUTH_ENABLED") != "true" or not session_secret:
        raise APIError(503, "demo_disabled", "Demo sessions are disabled. Configure identity before accepting requests.")
    id = data.buyerId or f"buyer-{uuid4()}"
    if data.role == "provider":
        if not data.businessId or not store.get("business", data.businessId):
            raise APIError(404, "not_found", "Sample business not found.")
        id = data.businessId
    payload = base64.urlsafe_b64encode(json.dumps({"id":id,"role":data.role,"exp":time.time()+86400}).encode()).decode().rstrip("=")
    signature = hmac.new(session_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return {"token":f"{payload}.{signature}","id":id,"role":data.role}

@app.get("/projects")
def projects():
    order = {business["id"]: i for i, business in enumerate(CATALOG["businesses"])}
    return {"projects":[expose_project(p) for p in sorted(store.list("project"), key=lambda p:p["createdAt"], reverse=True)], "businesses":sorted(store.list("business"), key=lambda b:order.get(b["id"], len(order)))}

@app.get("/businesses/{id}")
def business(id: str):
    record = store.get("business", id)
    if not record:
        raise APIError(404, "not_found", "Business not found.")
    return {"business":record, "projects":[expose_project(p) for p in store.list("project") if p["businessId"] == id]}

@app.post("/projects", status_code=201)
def post_project(data: ProjectInput, user=Depends(actor)):
    require_role(user, "provider")
    image = data.image
    allowed = image in {project["image"] for project in CATALOG["projects"]}
    if os.getenv("BUCKET_NAME"):
        allowed = allowed or image.startswith(f"projects/{user['id']}/")
    else:
        allowed = allowed or image.startswith(("data:image/png;base64,", "data:image/jpeg;base64,", "data:image/webp;base64,"))
    if not allowed:
        raise APIError(422, "invalid_image", "Use an uploaded project image.")
    record = {**data.model_dump(),"id":str(uuid4()),"businessId":user["id"],"createdAt":now(),"services":[data.category],"resultNote":"Provider-supplied result for this sample business.","color":"#ece9df","featured":False,
              "completed":True,"publicShareable":True,"status":"completed","visibility":"public","provenance":"provider_reported","evidenceVersion":1}
    store.put("project", record, create=True)
    return expose_project(record)

class UploadInput(BaseModel):
    contentType: str = Field(pattern="^image/(png|jpeg|webp)$")

@app.post("/uploads")
def upload(data: UploadInput, user=Depends(actor)):
    require_role(user, "provider")
    if not os.getenv("BUCKET_NAME"):
        raise APIError(503, "storage_unavailable", "S3 is not configured.")
    import boto3
    key = f"projects/{user['id']}/{uuid4()}"
    url = boto3.client("s3").generate_presigned_url("put_object", Params={"Bucket":os.environ["BUCKET_NAME"],"Key":key,"ContentType":data.contentType}, ExpiresIn=300)
    return {"url":url,"key":key}

@app.post("/briefs", status_code=201)
def brief(data: BuyerInput, user=Depends(actor)):
    require_role(user, "buyer")
    project = store.get("project", data.projectId)
    if not project:
        raise APIError(404, "not_found", "Selected project no longer exists.")
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        # Return quickly; API Gateway must not wait for a multi-step agent run.
        import boto3
        job = {"id":str(uuid4()),"buyerId":user["id"],"projectId":project["id"],"businessId":project["businessId"],"input":data.model_dump(mode="json"),"status":"pending","createdAt":now()}
        store.put("job", job, create=True)
        boto3.client("lambda").invoke(FunctionName=os.environ["AWS_LAMBDA_FUNCTION_NAME"], InvocationType="Event", Payload=json.dumps({"_dealfeedBriefJob":job["id"]}).encode())
        return JSONResponse(status_code=202, content={"jobId":job["id"],"status":"pending"})
    try:
        generated, trace, mode = generate_draft(store, data.model_dump(mode="json"))
    except InferenceUnavailable as exc:
        raise APIError(503, "inference_unavailable", str(exc))
    record = {"id":str(uuid4()),"buyerId":user["id"],"projectId":project["id"],"businessId":project["businessId"],"input":data.model_dump(mode="json"),"brief":generated,"trace":trace,"mode":mode,"createdAt":now()}
    return store.put("draft", record, create=True)

@app.get("/briefs/{id}")
def brief_status(id: str, user=Depends(actor)):
    require_role(user, "buyer")
    job = store.get("job", id)
    if not job or job["buyerId"] != user["id"]:
        raise APIError(404, "not_found", "Brief not found.")
    if job["status"] == "failed" or (job["status"] == "pending" and (datetime.now(timezone.utc)-datetime.fromisoformat(job["createdAt"])).total_seconds()>180):
        raise APIError(503, "inference_unavailable", "Brief generation could not finish. Your details are preserved; please retry.")
    return {"status":job["status"], **({"draft":store.get("draft", id)} if job["status"] == "complete" else {})}

@app.post("/requests", status_code=201)
def approve(data: Approval, user=Depends(actor)):
    require_role(user, "buyer")
    draft = store.get("draft", data.draftId)
    if not draft or draft["buyerId"] != user["id"]:
        raise APIError(404, "not_found", "Draft not found.")
    if not data.approved or data.brief.questions:
        raise APIError(422, "approval_required", "Resolve questions and approve the brief before sending.")
    existing = store.get("request", draft["id"])
    if existing:
        return existing
    edited = data.brief.model_dump()
    edited["reference"] = draft["brief"]["reference"]
    record = {**draft,"brief":edited,"status":"submitted","approvedAt":now(),"trace":[*draft["trace"],{"tool":"save_request","status":"complete","detail":"Saved after explicit buyer approval"}]}
    try:
        return save_approved_request(store, record, user["id"], data.approved)
    except Conflict:
        return store.get("request", draft["id"])

@app.get("/requests")
def requests(user=Depends(actor)):
    key = "buyerId" if user["role"] == "buyer" else "businessId"
    result = []
    for record in store.list("request"):
        if record[key] == user["id"]:
            proposal = store.get("proposal", record["id"])
            result.append({**record,"status":"proposed" if proposal else "submitted", **({"proposal":proposal} if proposal else {})})
    return {"requests":sorted(result, key=lambda r:r["createdAt"], reverse=True)}

@app.post("/requests/{id}/proposal", status_code=201)
def proposal(id: str, data: ProposalInput, user=Depends(actor)):
    require_role(user, "provider")
    record = get_owned_request(id, user)
    allowed_deliverables = {item["id"] for item in record.get("criteria", {}).get("deliverables", [])}
    if any(item.deliverableId not in allowed_deliverables for item in data.coverage):
        raise APIError(422, "invalid_deliverable", "Coverage must refer to deliverables in this approved request.")
    for project_id in data.comparableProjectIds:
        project = store.get("project", project_id)
        if (not project or project["businessId"] != user["id"] or project.get("archived")
                or project.get("status") != "completed" or project.get("visibility") != "public"
                or project.get("completed") is False or project.get("publicShareable") is False):
            raise APIError(422, "invalid_evidence", "Comparable projects must be publicly shared completed work from your business.")
    business = store.get("business", user["id"]) or {}
    achievement_ids = {item["id"] for item in business.get("achievements", []) if isinstance(item, dict) and item.get("id")}
    for achievement_id in data.achievementIds:
        achievement = store.get("achievement", achievement_id)
        if achievement_id not in achievement_ids and (not achievement or achievement.get("businessId") != user["id"]):
            raise APIError(422, "invalid_evidence", "Achievement references must belong to your business.")
    price_cents = int((Decimal(str(data.price)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    result = {**data.model_dump(),"price":price_cents / 100,"priceCents":price_cents,"version":1,"id":id,"requestId":id,"buyerId":record["buyerId"],"businessId":record["businessId"],"createdAt":now()}
    if record.get("dealId"):
        result["dealId"] = record["dealId"]
    try:
        return store.put("proposal", result, create=True)
    except Conflict:
        raise APIError(409, "proposal_exists", "This request already has a proposal. Refresh to see it.")

@app.get("/requests/{id}")
def request_detail(id: str, user=Depends(actor)):
    record = get_owned_request(id, user)
    response = store.get("proposal", id)
    return {**record, "status": "proposed" if response else "submitted", **({"proposal": response} if response else {})}

def generate_matches(store, criteria):
    from .matching import generate_matches as generate
    return generate(store, criteria)

def compare_deal(store, deal, proposals):
    from .matching import compare_deal as compare
    return compare(store, deal, proposals)

def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def evidence_fingerprint(business_ids):
    from . import matching
    if hasattr(matching, "evidence_fingerprint"):
        return matching.evidence_fingerprint(store, business_ids)
    wanted = set(business_ids)
    return fingerprint({
        "businesses": sorted([row for row in store.list("business") if row["id"] in wanted], key=lambda row: row["id"]),
        "projects": sorted([row for row in store.list("project") if row.get("businessId") in wanted], key=lambda row: row["id"]),
        "research": sorted([row for row in store.list("research") if row.get("businessId") in wanted], key=lambda row: row["id"]),
    })

def owned_deal(id, user):
    require_role(user, "buyer")
    record = store.get("deal", id)
    if not record or record["buyerId"] != user["id"]:
        raise APIError(404, "not_found", "Deal not found.")
    return record

def deal_proposals(deal):
    return [proposal for id in deal["requestIds"] if (proposal := store.get("proposal", id))]

def comparison_fingerprint(deal, proposals):
    return fingerprint({"brief": deal["approvedBrief"], "proposals": sorted(proposals, key=lambda row: row["id"]), "evidence": evidence_fingerprint(deal["businessIds"])})

def expose_deal(deal):
    responses = deal_proposals(deal)
    by_request = {response["requestId"]: response for response in responses}
    requests = []
    for id in deal["requestIds"]:
        record = store.get("request", id)
        if record:
            requests.append({**record, "status": "proposed" if id in by_request else "submitted", **({"proposal": by_request[id]} if id in by_request else {})})
    comparison = deal.get("comparison")
    comparison_status = deal.get("comparisonStatus", "not_started")
    if comparison_status == "pending" and deal.get("comparisonJobId"):
        job = store.get("marketplace_job", deal["comparisonJobId"])
        if not job or job["status"] == "failed" or (datetime.now(timezone.utc) - datetime.fromisoformat(job["createdAt"])).total_seconds() > 300:
            comparison_status = "failed"
    if comparison and comparison.get("inputFingerprint") != comparison_fingerprint(deal, responses):
        comparison = None
        if comparison_status not in ("pending", "failed"):
            comparison_status = "stale"
    elif comparison:
        comparison_status = "complete"
    run = store.get("match", deal["matchRunId"]) or {}
    result = {**deal, "requests": requests, "proposals": responses, "matches": run.get("matches", []),
              "status": "selected" if deal.get("selectedRequestId") else ("responses_received" if responses else "awaiting_responses"),
              "comparison": comparison, "comparisonStatus": comparison_status}
    result.pop("approvalFingerprint", None)
    result.pop("idempotencyKey", None)
    return result

def save_match_result(id, buyer_id, criteria, created_at):
    generated = generate_matches(store, criteria)
    matches = generated.get("matches", [])
    ids = [row.get("businessId") for row in matches]
    if len(ids) > 5 or len(ids) != len(set(ids)) or any(not id or not store.get("business", id) for id in ids):
        raise InferenceUnavailable("The analysis contained invalid businesses. Your requirements are saved; please retry.")
    record = {**generated, "id": id, "buyerId": buyer_id, "criteria": criteria, "createdAt": created_at,
              "status": "complete", "version": 1, "evidenceFingerprint": evidence_fingerprint(ids)}
    return store.put("match", record, create=True)

def async_analysis_enabled():
    return bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME")) or os.getenv("ASYNC_ANALYSIS", "").lower() == "true"

def dispatch_marketplace_job(job, background_tasks=None):
    store.put("marketplace_job", job, create=True)
    try:
        if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
            import boto3
            boto3.client("lambda").invoke(FunctionName=os.environ["AWS_LAMBDA_FUNCTION_NAME"], InvocationType="Event", Payload=json.dumps({"_dealfeedMarketplaceJob": job["id"]}).encode())
        elif background_tasks is not None:
            # Starlette runs synchronous background work in its thread pool
            # after delivering the 202 response. The durable record allows a
            # refreshed browser to recover completed, failed, or stalled work.
            background_tasks.add_task(process_marketplace_job, job["id"])
        else:
            raise RuntimeError("Local analysis needs a background task context.")
    except Exception:
        store.put("marketplace_job", {**job, "status": "failed"})
        raise APIError(503, "inference_unavailable", "Analysis could not start. Your requirements are preserved; please retry.")
    return JSONResponse(status_code=202, content={"jobId": job["id"], "status": "pending"})

@app.post("/matches", status_code=201)
def match_businesses(data: MatchInput, background_tasks: BackgroundTasks, user=Depends(actor)):
    require_role(user, "buyer")
    criteria = data.criteria.model_dump(mode="json")
    if not criteria["preferencesConfirmed"]:
        raise APIError(422, "preferences_need_confirmation", "Review the editable requirements and confirm your preferences before analysis.")
    for id in criteria["inspirationProjectIds"]:
        project = store.get("project", id)
        if (not project or project.get("archived") or project.get("completed") is False or project.get("publicShareable") is False
                or project.get("status") != "completed" or project.get("visibility") != "public"):
            raise APIError(422, "invalid_inspiration", "Choose available, publicly shared completed work as inspiration.")
    id, created_at = str(uuid4()), now()
    if async_analysis_enabled():
        return dispatch_marketplace_job({"id": id, "type": "match", "buyerId": user["id"], "criteria": criteria, "createdAt": created_at, "status": "pending"}, background_tasks)
    try:
        return save_match_result(id, user["id"], criteria, created_at)
    except (InferenceUnavailable, ValueError) as exc:
        raise APIError(503, "inference_unavailable", str(exc))

@app.get("/matches/{id}")
def match_detail(id: str, user=Depends(actor)):
    require_role(user, "buyer")
    run = store.get("match", id)
    if run and run["buyerId"] == user["id"]:
        return run
    job = store.get("marketplace_job", id)
    if not job or job["buyerId"] != user["id"] or job.get("type") != "match":
        raise APIError(404, "not_found", "Match analysis not found.")
    elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(job["createdAt"])).total_seconds()
    if job["status"] == "failed" or elapsed > 300:
        raise APIError(503, "inference_unavailable", "Analysis could not finish. Your requirements are preserved; please retry.")
    return {"id": id, "status": "pending", "criteria": job["criteria"]}

@app.post("/deals", status_code=201)
def approve_deal(data: DealApproval, user=Depends(actor)):
    require_role(user, "buyer")
    if not data.approved:
        raise APIError(422, "approval_required", "Approve the shared request before inviting businesses.")
    approval_fingerprint = fingerprint({"matchRunId": data.matchRunId, "businessIds": sorted(data.businessIds), "approved": True})
    key = fingerprint({"buyerId": user["id"], "key": data.idempotencyKey})
    existing = store.get("idempotency", key)
    if existing:
        if existing["fingerprint"] != approval_fingerprint:
            raise APIError(409, "idempotency_conflict", "This approval key was already used for different recipients or requirements.")
        return expose_deal(store.get("deal", existing["dealId"]))
    run = store.get("match", data.matchRunId)
    if not run or run["buyerId"] != user["id"]:
        raise APIError(404, "not_found", "Match analysis not found.")
    shortlisted = {match["businessId"] for match in run["matches"]}
    if not set(data.businessIds).issubset(shortlisted):
        raise APIError(422, "invalid_recipient", "Invite only businesses from this validated shortlist.")
    if run.get("evidenceFingerprint") != evidence_fingerprint(list(shortlisted)):
        raise APIError(409, "analysis_stale", "Business evidence changed. Refresh the match analysis before approving.")
    criteria, created_at, id = run["criteria"], now(), str(uuid4())
    budget_text = f"{criteria['currency']} {criteria['budgetCents'] / 100:.2f}" if criteria.get("budgetCents") is not None else "Not specified"
    projects = [store.get("project", project_id) for project_id in criteria["inspirationProjectIds"]]
    brief = {"title": f"{criteria['serviceCategory']} request" + (f" for {criteria['buyerName']}" if criteria.get("buyerName") else ""),
             "summary": criteria["description"], "deliverables": [item["label"] for item in criteria["deliverables"]],
             "questions": [], "constraints": [*criteria["mustHaves"], f"Buyer budget: {budget_text}; provider quote required."],
             "reference": "; ".join(project["title"] for project in projects if project)}
    buyer_input = {"name": criteria.get("buyerName") or "Customer", "budget": budget_text,
                   "location": criteria.get("location") or criteria["deliveryMode"], "deadline": criteria.get("targetDate") or "To confirm",
                   "requirements": criteria["description"], "projectId": criteria["inspirationProjectIds"][0]}
    requests = [{"id": str(uuid4()), "dealId": id, "buyerId": user["id"], "businessId": business_id,
                 "projectId": criteria["inspirationProjectIds"][0], "input": buyer_input, "criteria": criteria,
                 "approvedBrief": criteria, "brief": brief, "briefVersion": 1, "createdAt": created_at, "approvedAt": created_at,
                 "status": "submitted", "mode": run.get("mode", "unknown"), "trace": [{"tool": "approve_deal", "status": "complete", "detail": "Shared brief explicitly approved by the customer."}]}
                for business_id in data.businessIds]
    deal = {"id": id, "buyerId": user["id"], "matchRunId": data.matchRunId, "criteria": criteria, "approvedBrief": criteria,
            "briefVersion": 1, "businessIds": data.businessIds, "requestIds": [row["id"] for row in requests],
            "createdAt": created_at, "approvedAt": created_at, "selectedRequestId": None, "selectedBusinessId": None,
            "comparison": None, "comparisonStatus": "not_started", "mode": run.get("mode", "unknown")}
    receipt = {"id": key, "buyerId": user["id"], "dealId": id, "fingerprint": approval_fingerprint, "createdAt": created_at}
    try:
        store.atomic_create([("idempotency", receipt), ("deal", deal), *[("request", row) for row in requests]])
    except Conflict:
        existing = store.get("idempotency", key)
        if not existing or existing["fingerprint"] != approval_fingerprint:
            raise APIError(409, "idempotency_conflict", "Approval changed or is already being processed. Refresh and retry.")
        deal = store.get("deal", existing["dealId"])
    return expose_deal(deal)

@app.get("/deals")
def deals(user=Depends(actor)):
    require_role(user, "buyer")
    rows = [expose_deal(row) for row in store.list("deal") if row["buyerId"] == user["id"]]
    return {"deals": sorted(rows, key=lambda row: row["createdAt"], reverse=True)}

@app.get("/deals/{id}")
def deal_detail(id: str, user=Depends(actor)):
    return expose_deal(owned_deal(id, user))

def save_comparison(deal):
    proposals = deal_proposals(deal)
    input_fingerprint = comparison_fingerprint(deal, proposals)
    generated = compare_deal(store, deal, proposals)
    # Research may refresh during analysis. Stamp the source version that the
    # generated result actually used, without hiding concurrent source changes.
    if generated.get("evidenceVersion") == evidence_fingerprint(deal["businessIds"]):
        input_fingerprint = comparison_fingerprint(deal, proposals)
    result = {**generated, "id": str(uuid4()), "version": 1, "createdAt": now(), "inputFingerprint": input_fingerprint}
    def persist(current):
        if comparison_fingerprint(current, deal_proposals(current)) != input_fingerprint:
            raise Conflict("Responses or evidence changed during comparison.")
        return {**current, "comparison": result, "comparisonStatus": "complete"}
    store.update("deal", deal["id"], persist)
    return result

@app.post("/deals/{id}/compare")
def compare(id: str, background_tasks: BackgroundTasks, user=Depends(actor)):
    deal = owned_deal(id, user)
    proposals = deal_proposals(deal)
    if not proposals:
        raise APIError(422, "proposal_required", "Wait for at least one provider response before comparing.")
    if deal.get("comparison") and deal["comparison"].get("inputFingerprint") == comparison_fingerprint(deal, proposals):
        return deal["comparison"]
    if async_analysis_enabled():
        if deal.get("comparisonStatus") == "pending" and deal.get("comparisonJobId"):
            existing_job = store.get("marketplace_job", deal["comparisonJobId"])
            if existing_job and existing_job["status"] in ("pending", "running") and (datetime.now(timezone.utc) - datetime.fromisoformat(existing_job["createdAt"])).total_seconds() <= 300:
                return JSONResponse(status_code=202, content={"jobId": existing_job["id"], "status": "pending"})
        job_id = str(uuid4())
        store.update("deal", id, lambda current: {**current, "comparisonStatus": "pending", "comparisonJobId": job_id})
        try:
            return dispatch_marketplace_job({"id": job_id, "type": "comparison", "buyerId": user["id"], "dealId": id, "createdAt": now(), "status": "pending"}, background_tasks)
        except APIError:
            store.update("deal", id, lambda current: {**current, "comparisonStatus": "failed"})
            raise
    try:
        return save_comparison(deal)
    except Conflict:
        raise APIError(409, "analysis_stale", "Responses or evidence changed during analysis. Compare again to include the latest inputs.")
    except (InferenceUnavailable, ValueError) as exc:
        raise APIError(503, "inference_unavailable", str(exc))

@app.post("/deals/{id}/selection")
def select_provider(id: str, data: SelectionInput, user=Depends(actor)):
    deal = owned_deal(id, user)
    if data.requestId not in deal["requestIds"] or not store.get("proposal", data.requestId):
        raise APIError(422, "proposal_required", "Choose a provider that submitted a proposal for this deal.")
    selected = store.get("request", data.requestId)
    def choose(current):
        if current.get("selectedRequestId") == data.requestId:
            return current
        return {**current, "selectedRequestId": data.requestId, "selectedBusinessId": selected["businessId"], "selectedAt": now(),
                "selectionMeaning": "Customer preference only; no payment or contractual acceptance."}
    return expose_deal(store.update("deal", id, choose))

def process_marketplace_job(id):
    def claim(job):
        if job["status"] != "pending":
            raise Conflict()
        return {**job, "status": "running", "startedAt": now()}
    try:
        job = store.update("marketplace_job", id, claim)
    except (Conflict, KeyError):
        return {"ok": True}
    try:
        if job["type"] == "match":
            save_match_result(job["id"], job["buyerId"], job["criteria"], job["createdAt"])
        else:
            save_comparison(store.get("deal", job["dealId"]))
        store.put("marketplace_job", {**job, "status": "complete", "completedAt": now()})
    except Exception:
        store.put("marketplace_job", {**job, "status": "failed", "completedAt": now()})
        if job["type"] == "comparison":
            store.update("deal", job["dealId"], lambda current: {**current, "comparisonStatus": "failed"} if current.get("comparisonJobId") == id else current)
    return {"ok": True}

asgi_handler = Mangum(app, lifespan="off")

def handler(event, context):
    if "_dealfeedMarketplaceJob" in event:
        return process_marketplace_job(event["_dealfeedMarketplaceJob"])
    if "_dealfeedBriefJob" not in event:
        return asgi_handler(event, context)
    job = store.get("job", event["_dealfeedBriefJob"])
    if not job or job["status"] != "pending":
        return {"ok":True}
    try:
        generated, trace, mode = generate_draft(store, job["input"])
        draft = {key:job[key] for key in ["id","buyerId","projectId","businessId","input","createdAt"]}
        store.put("draft", {**draft,"brief":generated,"trace":trace,"mode":mode})
        store.put("job", {**job,"status":"complete"})
    except Exception:
        store.put("job", {**job,"status":"failed"})
    return {"ok":True}
