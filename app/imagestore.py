"""Copies of the images on Custom SOS package tickets.

Saved when a ticket is scanned, so the SOS Scans page can always show what was
on the ticket -- to anyone signed in here, without a Zendesk session, and even
after the attachment is removed from Zendesk.

On Spluki: the app's own bucket from the SPLUKI_STORAGE grant (STORAGE_BUCKET +
STORAGE_REGION injected; the task's IAM role is the credential -- no key).
Locally: app/images/ (gitignored), so the preview needs no AWS.
Same two-backend shape as the Extension Hub's storage.py.

Keys: sos/<ticket id>/<attachment id>/<file name>
"""
import os
import re

APP = os.path.dirname(os.path.abspath(__file__))


def key_for(ticket_id, attachment_id, filename):
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename or "image")[:120] or "image"
    return "sos/%d/%s/%s" % (int(ticket_id), re.sub(r"\D", "", str(attachment_id)) or "0", safe)


class LocalStore:
    def __init__(self, root):
        self.root = root

    def _p(self, key):
        return os.path.join(self.root, *key.split("/"))

    def get(self, key):
        try:
            with open(self._p(key), "rb") as f:
                return f.read()
        except OSError:
            return None

    def put(self, key, data, content_type):
        p = self._p(key)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)

    def describe(self):
        return "local folder"


class S3Store:
    def __init__(self, bucket, region):
        import boto3
        self.bucket = bucket
        self.s3 = boto3.client("s3", region_name=region)

    def get(self, key):
        try:
            return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self.s3.exceptions.NoSuchKey:
            return None

    def put(self, key, data, content_type):
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def describe(self):
        return "bucket"


_store = None


def store():
    global _store
    if _store is None:
        bucket = os.environ.get("STORAGE_BUCKET")
        _store = S3Store(bucket, os.environ.get("STORAGE_REGION") or None) if bucket else \
            LocalStore(os.environ.get("IMAGES_DIR") or os.path.join(APP, "images"))
    return _store
