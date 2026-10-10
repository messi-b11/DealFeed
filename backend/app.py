import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum
from pydantic import BaseModel, Field
from .models import BuyerInput, Approval, ProposalInput, ProjectInput
from .store import Store, Conflict
from .agent import generate_draft, save_approved_request, InferenceUnavailable, akamai_configured

app = FastAPI(title="DealFeed API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[os.getenv("ALLOWED_ORIGIN", "http://127.0.0.1:3000")], allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])
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
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
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
    return {"status":"ok", "mode":os.getenv("AI_MODE", "live"), "storage":"dynamodb" if store.table_name else "sqlite", "akamaiConfigured":akamai_configured(), "strandsMode":os.getenv("STRANDS_MODEL_MODE", "direct")}

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
    return {"projects":[expose_project(p) for p in sorted(store.list("project"), key=lambda p:p["createdAt"], reverse=True)], "businesses":store.list("business")}

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
    allowed = image in ["/projects/olive.svg", "/projects/forma.svg", "/projects/bloom.svg", "/projects/fieldwork.svg"]
    if os.getenv("BUCKET_NAME"):
        allowed = allowed or image.startswith(f"projects/{user['id']}/")
    else:
        allowed = allowed or image.startswith(("data:image/png;base64,", "data:image/jpeg;base64,", "data:image/webp;base64,"))
    if not allowed:
        raise APIError(422, "invalid_image", "Use an uploaded project image.")
    record = {**data.model_dump(),"id":str(uuid4()),"businessId":user["id"],"createdAt":now(),"services":["Website design"],"resultNote":"Provider-supplied result for this sample business.","color":"#ece9df","featured":False}
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
    result = {**data.model_dump(),"price":round(data.price,2),"id":id,"requestId":id,"buyerId":record["buyerId"],"businessId":record["businessId"],"createdAt":now()}
    try:
        return store.put("proposal", result, create=True)
    except Conflict:
        raise APIError(409, "proposal_exists", "This request already has a proposal. Refresh to see it.")

asgi_handler = Mangum(app, lifespan="off")

def handler(event, context):
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
