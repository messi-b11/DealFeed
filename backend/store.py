"""SQLite locally, DynamoDB in Lambda. Same records and ownership semantics."""
import json
import os
import sqlite3
from pathlib import Path

CATALOG = json.loads(Path(__file__).with_name("catalog.json").read_text())

class Conflict(Exception):
    pass

class Store:
    def __init__(self, path=None):
        self.table_name = os.getenv("TABLE_NAME") if path is None else None
        if self.table_name:
            import boto3
            self.table = boto3.resource("dynamodb").Table(self.table_name)
        else:
            self.path = path or os.getenv("DATABASE_PATH", ".local/dealfeed.sqlite")
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            with self.connect() as db:
                db.execute("CREATE TABLE IF NOT EXISTS records (pk TEXT PRIMARY KEY, kind TEXT NOT NULL, owner TEXT NOT NULL, data TEXT NOT NULL)")
                db.execute("CREATE INDEX IF NOT EXISTS records_kind ON records(kind, owner)")
        for kind, records in [("business", CATALOG["businesses"]), ("project", CATALOG["projects"])]:
            for record in records:
                try:
                    self.put(kind, record, create=True)
                except Conflict:
                    existing = self.get(kind, record["id"])
                    # Versioned fixtures are refreshed without replacing customer work.
                    if existing and record.get("seedVersion", 0) > existing.get("seedVersion", 0):
                        if existing.get("sample") or record.get("sample"):
                            self.put(kind, record)
                    # Retired samples remain addressable by existing requests and profiles.
                    # Only archive catalog-owned records; never delete user-created work.
                    if kind == "project" and record.get("archived"):
                        existing = self.get(kind, record["id"])
                        if existing and not existing.get("archived"):
                            self.put(kind, {**existing, "archived": True})

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def get(self, kind, id):
        pk = f"{kind}#{id}"
        if self.table_name:
            item = self.table.get_item(Key={"pk": pk}, ConsistentRead=True).get("Item")
            return json.loads(item["data"]) if item else None
        with self.connect() as db:
            row = db.execute("SELECT data FROM records WHERE pk=?", (pk,)).fetchone()
            return json.loads(row[0]) if row else None

    def list(self, kind, consistent=False):
        if self.table_name:
            from boto3.dynamodb.conditions import Key, Attr
            items, last = [], None
            while True:
                # The GSI is eventually consistent. Evidence invalidation uses
                # a base-table consistent snapshot so just-written research
                # cannot disappear from a comparison fingerprint.
                args = ({"FilterExpression": Attr("kind").eq(kind), "ConsistentRead": True} if consistent
                        else {"IndexName": "kind-index", "KeyConditionExpression": Key("kind").eq(kind)})
                if last:
                    args["ExclusiveStartKey"] = last
                page = self.table.scan(**args) if consistent else self.table.query(**args)
                items.extend(json.loads(item["data"]) for item in page["Items"])
                last = page.get("LastEvaluatedKey")
                if not last:
                    return items
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT data FROM records WHERE kind=?", (kind,))]

    def put(self, kind, record, create=False):
        item = {"pk": f"{kind}#{record['id']}", "kind": kind, "owner": record.get("buyerId", record.get("businessId", "catalog")), "data": json.dumps(record)}
        if self.table_name:
            args = {"Item": item}
            if create:
                args["ConditionExpression"] = "attribute_not_exists(pk)"
            try:
                self.table.put_item(**args)
            except self.table.meta.client.exceptions.ConditionalCheckFailedException as exc:
                raise Conflict() from exc
        else:
            with self.connect() as db:
                try:
                    db.execute(f"{'INSERT' if create else 'INSERT OR REPLACE'} INTO records VALUES (?, ?, ?, ?)", tuple(item.values()))
                except sqlite3.IntegrityError as exc:
                    raise Conflict() from exc
        return record

    def atomic_create(self, records):
        """Create a parent and all invitations together, or create none.

        The idempotency record participates in the same transaction, so retries
        cannot observe a successful approval without all of its invitations.
        """
        items = [
            {"pk": f"{kind}#{record['id']}", "kind": kind,
             "owner": record.get("buyerId", record.get("businessId", "catalog")),
             "data": json.dumps(record)}
            for kind, record in records
        ]
        if not items or len(items) > 100 or len({item["pk"] for item in items}) != len(items):
            raise ValueError("Atomic writes require 1–100 distinct records.")
        if self.table_name:
            import boto3
            client = boto3.client("dynamodb")
            try:
                client.transact_write_items(TransactItems=[{"Put": {
                    "TableName": self.table_name,
                    "Item": {key: {"S": value} for key, value in item.items()},
                    "ConditionExpression": "attribute_not_exists(pk)",
                }} for item in items])
            except client.exceptions.TransactionCanceledException as exc:
                if any(reason.get("Code") == "ConditionalCheckFailed" for reason in exc.response.get("CancellationReasons", [])):
                    raise Conflict() from exc
                raise
        else:
            with self.connect() as db:
                try:
                    db.execute("BEGIN IMMEDIATE")
                    for item in items:
                        db.execute("INSERT INTO records VALUES (?, ?, ?, ?)", tuple(item.values()))
                except sqlite3.IntegrityError as exc:
                    # The context manager rolls back all prior inserts.
                    raise Conflict() from exc
        return [record for _, record in records]

    def update(self, kind, id, transform):
        """Atomically transform an existing record without losing other updates.

        transform can raise Conflict to reject a state transition. DynamoDB
        retries only conditional races and uses a consistent read each time.
        """
        pk = f"{kind}#{id}"
        if self.table_name:
            for _ in range(5):
                item = self.table.get_item(Key={"pk": pk}, ConsistentRead=True).get("Item")
                if not item:
                    raise KeyError(id)
                updated = transform(json.loads(item["data"]))
                if updated.get("id") != id:
                    raise ValueError("Record identity cannot change.")
                try:
                    self.table.put_item(
                        Item={**item, "data": json.dumps(updated)},
                        ConditionExpression="#data = :previous",
                        ExpressionAttributeNames={"#data": "data"},
                        ExpressionAttributeValues={":previous": item["data"]},
                    )
                    return updated
                except self.table.meta.client.exceptions.ConditionalCheckFailedException:
                    continue
            raise Conflict("Concurrent update; retry.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM records WHERE pk=?", (pk,)).fetchone()
            if not row:
                raise KeyError(id)
            updated = transform(json.loads(row[0]))
            if updated.get("id") != id:
                raise ValueError("Record identity cannot change.")
            db.execute("UPDATE records SET data=? WHERE pk=?", (json.dumps(updated), pk))
            return updated
