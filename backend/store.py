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
                    pass

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

    def list(self, kind):
        if self.table_name:
            from boto3.dynamodb.conditions import Key
            items, last = [], None
            while True:
                args = {"IndexName": "kind-index", "KeyConditionExpression": Key("kind").eq(kind)}
                if last:
                    args["ExclusiveStartKey"] = last
                page = self.table.query(**args)
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
