import importlib
import os
from datetime import date, timedelta
import pytest
from fastapi.testclient import TestClient
from backend.store import Store
from backend.agent import InferenceUnavailable

os.environ.setdefault("AI_MODE", "rehearsal")
os.environ.setdefault("DEMO_AUTH_ENABLED", "true")
module = importlib.import_module("backend.app")

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_MODE", "rehearsal")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.setattr(module, "store", Store(str(tmp_path / "test.sqlite")))
    return TestClient(module.app)

def session(client, role="buyer", business=None, buyer=None):
    data={"role":role}
    if business:data["businessId"]=business
    if buyer:data["buyerId"]=buyer
    response=client.post("/sessions",json=data)
    assert response.status_code==200, response.text
    return {"Authorization":"Bearer "+response.json()["token"]}

def buyer_input():
    return {"projectId":"olive-table","name":"The Sunday Table","email":"owner@example.com","budget":"$3,000–$5,000","location":"Austin, TX","deadline":str(date.today()+timedelta(days=60)),"requirements":"A five-page restaurant website with a seasonal menu, our story, and a reservation link. We provide copy and photos."}

def draft(client, user):
    response=client.post("/briefs",json=buyer_input(),headers=user)
    assert response.status_code==201,response.text
    return response.json()

def submit(client, user, d):
    return client.post("/requests",headers=user,json={"draftId":d["id"],"approved":True,"brief":d["brief"]})

def proposal_input():
    return {"price":4500,"currency":"USD","scope":"Five-page responsive website, reservation link, two revisions, and handover. Buyer supplies copy and photos.","timeline":"Four weeks after kickoff and receipt of content."}

def test_full_flow_preserves_ownership_and_survives_store_reopen(client, monkeypatch):
    buyer=session(client,buyer="buyer-sunday-table"),
    buyer=buyer[0]
    d=draft(client,buyer)
    assert d["projectId"]=="olive-table"
    assert d["businessId"]=="studio-north"
    assert client.get("/requests",headers=buyer).json()["requests"]==[]
    d["brief"]["summary"] += " Include a dedicated private dining page."
    r=submit(client,buyer,d)
    assert r.status_code==201,r.text
    assert "private dining" in r.json()["brief"]["summary"]
    provider=session(client,"provider","studio-north")
    inbox=client.get("/requests",headers=provider).json()["requests"]
    assert len(inbox)==1 and inbox[0]["id"]==d["id"]
    response=client.post(f"/requests/{d['id']}/proposal",json=proposal_input(),headers=provider)
    assert response.status_code==201,response.text
    monkeypatch.setattr(module,"store",Store(module.store.path))
    rows=client.get("/requests",headers=buyer).json()["requests"]
    assert rows[0]["status"]=="proposed"
    assert rows[0]["proposal"]["price"]==4500
    assert rows[0]["proposal"]["buyerId"]==d["buyerId"]

@pytest.mark.parametrize("field",["budget","location","deadline","requirements","name","email"])
def test_missing_information_requests_clarification(client,field):
    body=buyer_input();body[field]=""
    response=client.post("/briefs",json=body,headers=session(client))
    assert response.status_code==422
    assert field in response.json()["error"]["fields"]
    assert module.store.list("request")==[]

def test_past_deadline_rejected(client):
    body=buyer_input();body["deadline"]="2000-01-01"
    assert client.post("/briefs",json=body,headers=session(client)).status_code==422

def test_approval_required_and_questions_block_submission(client):
    buyer=session(client);d=draft(client,buyer)
    body={"draftId":d["id"],"approved":False,"brief":d["brief"]}
    assert client.post("/requests",json=body,headers=buyer).status_code==422
    body["approved"]=True;body["brief"]["questions"]=["How many pages do you need?"]
    assert client.post("/requests",json=body,headers=buyer).status_code==422
    assert module.store.list("request")==[]

def test_cross_buyer_and_provider_access_blocked(client):
    buyer=session(client);other=session(client);d=draft(client,buyer)
    assert submit(client,other,d).status_code==404
    assert submit(client,buyer,d).status_code==201
    assert client.get("/requests",headers=other).json()["requests"]==[]
    wrong_provider=session(client,"provider","form-function")
    assert client.get("/requests",headers=wrong_provider).json()["requests"]==[]
    assert client.post(f"/requests/{d['id']}/proposal",json=proposal_input(),headers=wrong_provider).status_code==404
    assert client.post(f"/requests/{d['id']}/proposal",json=proposal_input(),headers=buyer).status_code==403

def test_duplicate_submission_idempotent_and_proposal_immutable(client):
    buyer=session(client);d=draft(client,buyer)
    assert submit(client,buyer,d).json()["id"]==submit(client,buyer,d).json()["id"]
    assert len(module.store.list("request"))==1
    provider=session(client,"provider","studio-north")
    for expected in [201,409]:
        assert client.post(f"/requests/{d['id']}/proposal",json=proposal_input(),headers=provider).status_code==expected

def test_inference_failure_is_recoverable_and_does_not_save_request(client,monkeypatch):
    original=module.generate_draft
    def fail(*args):raise InferenceUnavailable("Please retry.")
    monkeypatch.setattr(module,"generate_draft",fail)
    user=session(client)
    result=client.post("/briefs",json=buyer_input(),headers=user)
    assert result.status_code==503
    assert result.json()["error"]["code"]=="inference_unavailable"
    assert not module.store.list("request") and not module.store.list("draft")
    monkeypatch.setattr(module,"generate_draft",original)
    assert client.post("/briefs",json=buyer_input(),headers=user).status_code==201

def test_live_mode_does_not_fall_back_to_sample(client,monkeypatch):
    monkeypatch.setenv("AI_MODE","live")
    for name in ["AKAMAI_BASE_URL","AKAMAI_API_KEY","AKAMAI_MODEL"]:monkeypatch.delenv(name,raising=False)
    response=client.post("/briefs",json=buyer_input(),headers=session(client))
    assert response.status_code==503
    assert not module.store.list("draft")

def test_provider_posts_completed_work_and_request_keeps_new_project(client):
    provider=session(client,"provider","form-function")
    data={"title":"A fresh website for Harbor Cafe","client":"Harbor Cafe","description":"Completed a responsive website with a seasonal menu and a reservation link.","category":"Restaurant","result":"Simplified the reservation journey","image":"/projects/olive.svg"}
    post=client.post("/projects",json=data,headers=provider)
    assert post.status_code==201,post.text
    project=post.json()
    assert project["businessId"]=="form-function"
    assert project["id"] in [p["id"] for p in client.get("/projects").json()["projects"]]
    body=buyer_input();body["projectId"]=project["id"]
    result=client.post("/briefs",json=body,headers=session(client)).json()
    assert result["businessId"]=="form-function"
    assert result["projectId"]==project["id"]

def test_tampered_relationships_rejected(client):
    buyer=session(client);body=buyer_input();body["businessId"]="form-function"
    assert client.post("/briefs",json=body,headers=buyer).status_code==422
    d=draft(client,buyer);d["brief"]["reference"]="Incorrect reference"
    assert submit(client,buyer,d).json()["brief"]["reference"]=="A fresh digital home for Olive & Table"

def test_invalid_proposal_and_unauthenticated_access(client):
    assert client.get("/requests").status_code==401
    buyer=session(client);d=draft(client,buyer);submit(client,buyer,d)
    provider=session(client,"provider","studio-north")
    for price in [0,-1,0.001,1000001]:
        data=proposal_input();data["price"]=price
        assert client.post(f"/requests/{d['id']}/proposal",json=data,headers=provider).status_code==422

def test_async_job_ownership_completion_and_failure(client,monkeypatch):
    buyer=session(client);d=draft(client,buyer)
    job={k:d[k] for k in ["id","buyerId","projectId","businessId","input","createdAt"]}
    module.store.put("job",{**job,"status":"pending"})
    assert client.get(f"/briefs/{d['id']}",headers=session(client)).status_code==404
    assert client.get(f"/briefs/{d['id']}",headers=buyer).json()["status"]=="pending"
    module.handler({"_dealfeedBriefJob":d["id"]},None)
    response=client.get(f"/briefs/{d['id']}",headers=buyer).json()
    assert response["status"]=="complete" and response["draft"]["projectId"]=="olive-table"
    module.store.put("job",{**job,"status":"pending"})
    def fail(*args):raise InferenceUnavailable("Provider unavailable")
    monkeypatch.setattr(module,"generate_draft",fail)
    module.handler({"_dealfeedBriefJob":d["id"]},None)
    assert client.get(f"/briefs/{d['id']}",headers=buyer).status_code==503
