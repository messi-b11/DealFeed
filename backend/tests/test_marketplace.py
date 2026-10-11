"""Marketplace invariants independent of inference nondeterminism."""
import importlib
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.agent import InferenceUnavailable
from backend.store import Conflict, Store

os.environ.setdefault("AI_MODE", "rehearsal")
os.environ.setdefault("DEMO_AUTH_ENABLED", "true")
module = importlib.import_module("backend.app")
BUSINESSES = ["studio-north", "juniper-digital", "form-function", "morrow-studio", "common-ground-web"]


def criteria():
    return {
        "inspirationProjectIds": ["poppy-web"],
        "description": "A restaurant website with menus and an accessible reservation link.",
        "serviceCategory": "Website development", "budgetCents": 500000, "currency": "USD",
        "deliverables": [{"id": "site", "label": "Responsive website", "mandatory": True},
                         {"id": "booking", "label": "Reservation integration", "mandatory": True}],
        "keywords": ["warm"], "mustHaves": ["Reservation integration"],
        "desiredStandard": "Accessible and mobile friendly", "deliveryMode": "remote",
        "targetDate": str(date.today() + timedelta(days=60)), "preferencesConfirmed": True,
    }


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("AI_MODE", "rehearsal")
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.setattr(module, "store", Store(str(tmp_path / "marketplace.sqlite")))
    monkeypatch.setattr(module, "generate_matches", lambda store, criteria: {
        "matches": [{"businessId": id, "whyMatch": "Evidence from comparable completed work"} for id in BUSINESSES],
        "shortfallReason": None, "mode": "rehearsal", "trace": [], "evidenceVersion": "fixture-v1",
    })
    monkeypatch.setattr(module, "evidence_fingerprint", lambda ids: "stable-evidence")
    monkeypatch.setattr(module, "compare_deal", lambda store, deal, proposals: {
        "mode": "rehearsal", "trace": [], "rows": [{"requestId": p["requestId"], "priceCents": p["priceCents"]} for p in proposals],
    })
    return TestClient(module.app)


def auth(client, role="buyer", business=None):
    response = client.post("/sessions", json={"role": role, **({"businessId": business} if business else {})})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["token"]}


def match(client, buyer, body=None):
    response = client.post("/matches", headers=buyer, json={"criteria": body or criteria()})
    assert response.status_code == 201, response.text
    return response.json()


def approve(client, buyer, run, count=5, key="approval-001"):
    response = client.post("/deals", headers=buyer, json={"matchRunId": run["id"], "businessIds": BUSINESSES[:count], "approved": True, "idempotencyKey": key})
    assert response.status_code == 201, response.text
    return response.json()


def proposal(client, request, **extra):
    provider = auth(client, "provider", request["businessId"])
    body = {"price": 4100.25, "currency": "USD", "scope": "Responsive restaurant website with menu and reservation link.",
            "timeline": "Four weeks after content arrives", "fitStatement": "We build restaurant websites.",
            "approach": "Design review, implementation and accessibility review.",
            "coverage": [{"deliverableId": "site", "status": "included", "detail": "Responsive design"}], **extra}
    return client.post(f"/requests/{request['id']}/proposal", headers=provider, json=body)


def test_complete_deal_workflow_freezes_brief_and_survives_restart(client, monkeypatch):
    buyer = auth(client)
    run = match(client, buyer)
    assert module.store.list("request") == []
    assert client.get(f"/matches/{run['id']}", headers=buyer).json() == run
    deal = approve(client, buyer, run)
    assert len(deal["requests"]) == 5
    assert len(set(deal["requestIds"])) == 5
    assert all(request["approvedBrief"] == run["criteria"] for request in deal["requests"])
    assert deal["approvedBrief"] == deal["criteria"] == run["criteria"]
    response = proposal(client, deal["requests"][0])
    assert response.status_code == 201, response.text
    assert response.json()["priceCents"] == 410025
    comparison = client.post(f"/deals/{deal['id']}/compare", headers=buyer)
    assert comparison.status_code == 200, comparison.text
    assert comparison.json()["inputFingerprint"]
    selected = client.post(f"/deals/{deal['id']}/selection", headers=buyer, json={"requestId": deal["requestIds"][0]})
    assert selected.status_code == 200, selected.text
    assert selected.json()["status"] == "selected"
    assert "no payment" in selected.json()["selectionMeaning"]
    selected_at = selected.json()["selectedAt"]
    repeated = client.post(f"/deals/{deal['id']}/selection", headers=buyer, json={"requestId": deal["requestIds"][0]})
    assert repeated.json()["selectedAt"] == selected_at
    monkeypatch.setattr(module, "store", Store(module.store.path))
    persisted = client.get(f"/deals/{deal['id']}", headers=buyer).json()
    assert persisted["selectedRequestId"] == deal["requestIds"][0]
    assert persisted["comparison"]["id"] == comparison.json()["id"]


def test_ownership_keeps_competitor_proposals_private(client):
    buyer, stranger = auth(client), auth(client)
    run = match(client, buyer)
    deal = approve(client, buyer, run, count=2)
    first, second = deal["requests"]
    assert proposal(client, first).status_code == 201
    assert proposal(client, second, price=3800).status_code == 201
    provider = auth(client, "provider", first["businessId"])
    assert client.get(f"/matches/{run['id']}", headers=stranger).status_code == 404
    assert client.get(f"/deals/{deal['id']}", headers=stranger).status_code == 404
    assert client.get("/deals", headers=stranger).json() == {"deals": []}
    assert client.get(f"/deals/{deal['id']}", headers=provider).status_code == 403
    assert client.get(f"/requests/{second['id']}", headers=provider).status_code == 404
    inbox = client.get("/requests", headers=provider).json()["requests"]
    assert len(inbox) == 1 and inbox[0]["proposal"]["businessId"] == first["businessId"]
    assert "proposals" not in inbox[0] and "matches" not in inbox[0]
    assert client.post(f"/deals/{deal['id']}/compare", headers=provider).status_code == 403
    assert client.post(f"/deals/{deal['id']}/selection", headers=stranger, json={"requestId": first["id"]}).status_code == 404


def test_approval_retry_is_atomic_and_key_payload_cannot_change(client):
    buyer = auth(client)
    run = match(client, buyer)
    deal = approve(client, buyer, run)
    same = approve(client, buyer, run)
    assert same["id"] == deal["id"]
    assert len(module.store.list("deal")) == 1 and len(module.store.list("request")) == 5
    body = {"matchRunId": run["id"], "businessIds": BUSINESSES[:1], "approved": True, "idempotencyKey": "approval-001"}
    assert client.post("/deals", headers=buyer, json=body).status_code == 409
    body["businessIds"] = list(reversed(BUSINESSES))
    assert client.post("/deals", headers=buyer, json=body).json()["id"] == deal["id"]


def test_concurrent_approval_retries_create_only_one_invitation_set(client):
    buyer = auth(client)
    run = match(client, buyer)
    body = {"matchRunId": run["id"], "businessIds": BUSINESSES, "approved": True, "idempotencyKey": "parallel-approval"}
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda _: client.post("/deals", headers=buyer, json=body), range(6)))
    assert all(response.status_code == 201 for response in responses), [r.text for r in responses]
    assert len({response.json()["id"] for response in responses}) == 1
    assert len(module.store.list("request")) == 5


def test_atomic_store_rolls_back_partial_fanout(client):
    module.store.put("request", {"id": "existing", "buyerId": "owner"})
    with pytest.raises(Conflict):
        module.store.atomic_create([("deal", {"id": "must-rollback", "buyerId": "owner"}),
                                   ("request", {"id": "new-child", "buyerId": "owner"}),
                                   ("request", {"id": "existing", "buyerId": "owner"})])
    assert module.store.get("deal", "must-rollback") is None
    assert module.store.get("request", "new-child") is None
    assert module.store.get("request", "existing") is not None


@pytest.mark.parametrize("recipients,approved", [(BUSINESSES + ["gather-table"], True), ([], True), ([BUSINESSES[0]] * 2, True), (["unknown-provider"], True), (BUSINESSES, False)])
def test_invalid_approvals_leave_no_partial_work(client, recipients, approved):
    buyer = auth(client)
    run = match(client, buyer)
    result = client.post("/deals", headers=buyer, json={"matchRunId": run["id"], "businessIds": recipients, "approved": approved, "idempotencyKey": "invalid-approval"})
    assert result.status_code == 422, result.text
    assert module.store.list("deal") == [] and module.store.list("request") == []


def test_unknown_budget_is_preserved_and_confirmation_required(client):
    buyer = auth(client)
    body = criteria()
    body["budgetCents"] = None
    run = match(client, buyer, body)
    deal = approve(client, buyer, run, count=1)
    assert deal["approvedBrief"]["budgetCents"] is None
    assert deal["requests"][0]["input"]["budget"] == "Not specified"
    body["preferencesConfirmed"] = False
    result = client.post("/matches", headers=buyer, json={"criteria": body})
    assert result.status_code == 422


def test_criteria_rejects_unstable_deliverable_ids_and_bad_inspiration(client):
    buyer = auth(client)
    body = criteria()
    body["deliverables"][1]["id"] = "site"
    assert client.post("/matches", headers=buyer, json={"criteria": body}).status_code == 422
    body = criteria()
    body["inspirationProjectIds"] = ["missing"]
    assert client.post("/matches", headers=buyer, json={"criteria": body}).status_code == 422
    private = module.store.get("project", "poppy-web")
    module.store.put("project", {**private, "publicShareable": False})
    assert client.post("/matches", headers=buyer, json={"criteria": criteria()}).status_code == 422


def test_evidence_changes_require_new_analysis_before_approval(client, monkeypatch):
    buyer = auth(client)
    run = match(client, buyer)
    monkeypatch.setattr(module, "evidence_fingerprint", lambda ids: "new-evidence")
    result = client.post("/deals", headers=buyer, json={"matchRunId": run["id"], "businessIds": BUSINESSES, "approved": True, "idempotencyKey": "stale-analysis"})
    assert result.status_code == 409 and result.json()["error"]["code"] == "analysis_stale"
    assert module.store.list("request") == []


def test_proposal_references_must_belong_to_request_and_provider(client):
    buyer = auth(client)
    deal = approve(client, buyer, match(client, buyer), count=1)
    request = deal["requests"][0]
    for extra in [{"coverage": [{"deliverableId": "invented", "status": "included"}]},
                  {"comparableProjectIds": ["poppy-web"]}, {"achievementIds": ["invented-achievement"]},
                  {"coverage": [{"deliverableId": "site", "status": "included"}] * 2}]:
        response = proposal(client, request, **extra)
        assert response.status_code == 422, response.text
    response = proposal(client, request)
    assert response.status_code == 201
    assert response.json()["coverage"] == [{"deliverableId": "site", "status": "included", "detail": "Responsive design"}]
    assert proposal(client, request).status_code == 409


def test_new_proposals_and_evidence_invalidate_comparison(client, monkeypatch):
    buyer = auth(client)
    deal = approve(client, buyer, match(client, buyer), count=2)
    assert proposal(client, deal["requests"][0]).status_code == 201
    first = client.post(f"/deals/{deal['id']}/compare", headers=buyer).json()
    assert client.post(f"/deals/{deal['id']}/compare", headers=buyer).json()["id"] == first["id"]
    assert proposal(client, deal["requests"][1]).status_code == 201
    stale = client.get(f"/deals/{deal['id']}", headers=buyer).json()
    assert stale["comparison"] is None and stale["comparisonStatus"] == "stale"
    second = client.post(f"/deals/{deal['id']}/compare", headers=buyer).json()
    assert second["id"] != first["id"] and len(second["rows"]) == 2
    monkeypatch.setattr(module, "evidence_fingerprint", lambda ids: "evidence-updated")
    assert client.get(f"/deals/{deal['id']}", headers=buyer).json()["comparison"] is None


def test_selection_requires_submitted_proposal_and_customer_action(client):
    buyer = auth(client)
    deal = approve(client, buyer, match(client, buyer), count=2)
    assert client.post(f"/deals/{deal['id']}/compare", headers=buyer).status_code == 422
    assert client.post(f"/deals/{deal['id']}/selection", headers=buyer, json={"requestId": deal["requestIds"][0]}).status_code == 422
    assert proposal(client, deal["requests"][0]).status_code == 201
    assert client.post(f"/deals/{deal['id']}/compare", headers=buyer).status_code == 200
    assert client.get(f"/deals/{deal['id']}", headers=buyer).json()["selectedRequestId"] is None
    assert client.post(f"/deals/{deal['id']}/selection", headers=buyer, json={"requestId": "unrelated"}).status_code == 422


def test_inference_failures_never_create_invitations(client, monkeypatch):
    buyer = auth(client)
    def unavailable(*args):
        raise InferenceUnavailable("No live inference configuration.")
    monkeypatch.setattr(module, "generate_matches", unavailable)
    result = client.post("/matches", headers=buyer, json={"criteria": criteria()})
    assert result.status_code == 503
    assert module.store.list("match") == [] and module.store.list("request") == []


def test_duplicate_async_delivery_does_not_rerun_analysis(client, monkeypatch):
    buyer = auth(client)
    token = module.actor(type("Request", (), {"headers": buyer})())
    job = {"id": "queued-match", "buyerId": token["id"], "type": "match", "criteria": criteria(), "createdAt": module.now(), "status": "pending"}
    module.store.put("marketplace_job", job)
    assert client.get("/matches/queued-match", headers=buyer).json()["status"] == "pending"
    module.handler({"_dealfeedMarketplaceJob": job["id"]}, None)
    assert client.get("/matches/queued-match", headers=buyer).json()["status"] == "complete"
    def forbidden(*args):
        raise AssertionError("Duplicate delivery reran analysis")
    monkeypatch.setattr(module, "generate_matches", forbidden)
    module.handler({"_dealfeedMarketplaceJob": job["id"]}, None)
    assert module.store.get("marketplace_job", job["id"])["status"] == "complete"


def test_stalled_comparison_is_reported_as_failed(client):
    buyer = auth(client)
    deal = approve(client, buyer, match(client, buyer), count=1)
    job_id = "stalled-comparison"
    module.store.put("marketplace_job", {"id": job_id, "buyerId": deal["buyerId"], "status": "running", "type": "comparison", "dealId": deal["id"],
                                         "createdAt": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()})
    module.store.update("deal", deal["id"], lambda row: {**row, "comparisonStatus": "pending", "comparisonJobId": job_id})
    assert client.get(f"/deals/{deal['id']}", headers=buyer).json()["comparisonStatus"] == "failed"


def test_dynamodb_atomic_write_uses_transaction_and_conditional_creates(monkeypatch):
    import boto3
    from botocore.stub import Stubber
    db = boto3.client("dynamodb", region_name="us-east-1", aws_access_key_id="testing", aws_secret_access_key="testing")
    store = Store.__new__(Store)
    store.table_name = "dealfeed-test"
    records = [("deal", {"id": "parent", "buyerId": "buyer-one"}),
               ("request", {"id": "child", "buyerId": "buyer-one", "businessId": "provider-one"})]
    import json
    expected = {"TransactItems": [{"Put": {
        "TableName": store.table_name,
        "Item": {"pk": {"S": f"{kind}#{record['id']}"}, "kind": {"S": kind},
                 "owner": {"S": "buyer-one"}, "data": {"S": json.dumps(record)}},
        "ConditionExpression": "attribute_not_exists(pk)",
    }} for kind, record in records]}
    monkeypatch.setattr(boto3, "client", lambda service: db)
    with Stubber(db) as stub:
        stub.add_response("transact_write_items", {}, expected)
        assert store.atomic_create(records) == [record for _, record in records]
        stub.assert_no_pending_responses()


def test_dynamodb_conditional_transaction_failure_maps_to_conflict(monkeypatch):
    import boto3
    from botocore.stub import Stubber
    db = boto3.client("dynamodb", region_name="us-east-1", aws_access_key_id="testing", aws_secret_access_key="testing")
    store = Store.__new__(Store)
    store.table_name = "dealfeed-test"
    monkeypatch.setattr(boto3, "client", lambda service: db)
    with Stubber(db) as stub:
        stub.add_client_error("transact_write_items", service_error_code="TransactionCanceledException",
                              modeled_fields={"CancellationReasons": [{"Code": "ConditionalCheckFailed", "Message": "Already exists"}]})
        with pytest.raises(Conflict):
            store.atomic_create([("deal", {"id": "parent", "buyerId": "buyer-one"})])
        stub.assert_no_pending_responses()


def test_dynamodb_capacity_error_is_not_misreported_as_idempotency_conflict(monkeypatch):
    import boto3
    from botocore.stub import Stubber
    db = boto3.client("dynamodb", region_name="us-east-1", aws_access_key_id="testing", aws_secret_access_key="testing")
    store = Store.__new__(Store)
    store.table_name = "dealfeed-test"
    monkeypatch.setattr(boto3, "client", lambda service: db)
    with Stubber(db) as stub:
        stub.add_client_error("transact_write_items", service_error_code="TransactionCanceledException",
                              modeled_fields={"CancellationReasons": [{"Code": "ProvisionedThroughputExceeded"}]})
        with pytest.raises(db.exceptions.TransactionCanceledException):
            store.atomic_create([("deal", {"id": "parent", "buyerId": "buyer-one"})])


def test_response_arriving_during_analysis_cannot_publish_stale_comparison(client, monkeypatch):
    buyer = auth(client)
    deal = approve(client, buyer, match(client, buyer), count=2)
    assert proposal(client, deal["requests"][0]).status_code == 201
    second = deal["requests"][1]
    def compare_with_arrival(store, deal, proposals):
        store.put("proposal", {"id": second["id"], "requestId": second["id"], "businessId": second["businessId"],
                               "buyerId": second["buyerId"], "dealId": deal["id"], "priceCents": 390000,
                               "price": 3900, "scope": "A newly arrived independent proposal", "timeline": "Four weeks", "createdAt": module.now()}, create=True)
        return {"mode": "rehearsal", "rows": [{"requestId": row["id"]} for row in proposals]}
    monkeypatch.setattr(module, "compare_deal", compare_with_arrival)
    response = client.post(f"/deals/{deal['id']}/compare", headers=buyer)
    assert response.status_code == 409 and response.json()["error"]["code"] == "analysis_stale"
    assert module.store.get("deal", deal["id"])["comparison"] is None


def test_local_async_matching_and_comparison_persist_recoverable_jobs(client, monkeypatch):
    buyer = auth(client)
    monkeypatch.setenv("ASYNC_ANALYSIS", "true")
    response = client.post("/matches", headers=buyer, json={"criteria": criteria()})
    assert response.status_code == 202, response.text
    job_id = response.json()["jobId"]
    # TestClient waits for Starlette background tasks; real HTTP receives 202 first.
    run = client.get(f"/matches/{job_id}", headers=buyer).json()
    assert run["status"] == "complete" and run["id"] == job_id
    assert module.store.get("marketplace_job", job_id)["status"] == "complete"
    assert client.get(f"/matches/{job_id}", headers=auth(client)).status_code == 404
    deal = approve(client, buyer, run, count=1)
    assert proposal(client, deal["requests"][0]).status_code == 201
    comparison = client.post(f"/deals/{deal['id']}/compare", headers=buyer)
    assert comparison.status_code == 202, comparison.text
    assert module.store.get("marketplace_job", comparison.json()["jobId"])["status"] == "complete"
    restored = client.get(f"/deals/{deal['id']}", headers=buyer).json()
    assert restored["comparisonStatus"] == "complete" and restored["comparison"]


def test_local_async_inference_failure_surfaces_without_losing_criteria(client, monkeypatch):
    buyer = auth(client)
    monkeypatch.setenv("ASYNC_ANALYSIS", "true")
    def unavailable(*args):
        raise InferenceUnavailable("Temporary upstream failure")
    monkeypatch.setattr(module, "generate_matches", unavailable)
    response = client.post("/matches", headers=buyer, json={"criteria": criteria()})
    assert response.status_code == 202
    job_id = response.json()["jobId"]
    job = module.store.get("marketplace_job", job_id)
    assert job["status"] == "failed" and job["criteria"]["description"] == criteria()["description"]
    failed = client.get(f"/matches/{job_id}", headers=buyer)
    assert failed.status_code == 503 and failed.json()["error"]["code"] == "inference_unavailable"
    assert module.store.list("request") == []


def test_stalled_local_match_job_surfaces_retryable_error(client):
    buyer = auth(client)
    identity = module.actor(type("Request", (), {"headers": buyer})())
    module.store.put("marketplace_job", {"id": "stalled-local-match", "buyerId": identity["id"], "type": "match", "criteria": criteria(),
                                         "createdAt": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(), "status": "running"})
    response = client.get("/matches/stalled-local-match", headers=buyer)
    assert response.status_code == 503
    assert module.store.get("marketplace_job", "stalled-local-match")["criteria"] == criteria()


def test_preview_basic_auth_and_app_session_header_coexist(client):
    buyer = auth(client)
    combined = {"Authorization": "Basic cHJldmlldzpwdWJsaWMtZGVtby1nYXRl", "X-DealFeed-Authorization": buyer["Authorization"]}
    assert client.get("/deals", headers=combined).status_code == 200
    assert client.get("/deals", headers={"Authorization": combined["Authorization"]}).status_code == 401
    # A forged custom identity must not fall back to a different valid identity.
    assert client.get("/deals", headers={**buyer, "X-DealFeed-Authorization": "Bearer invalid"}).status_code == 401
