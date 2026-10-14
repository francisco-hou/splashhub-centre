"""Downloads: the team's Chrome extensions (and other packages), moved here from
the Extension Hub app. Same catalogue and the same addresses, so the SplashHub
Add-On's update check and its "Update now" script only change host:

  GET  /api/list  (also /api/downloads/list)   the catalogue, {"items": [...]}
  GET  /d/<vid>/<file name>                     one version's file

Both are open: no sign-in, no admin -- the add-on and its .bat have no session,
and the Downloads page is reachable from the sign-in page. Adding, updating and
deleting need the Admin role (server.py).

Storage: this app's own bucket (SPLUKI_STORAGE, imagestore.py), under
downloads/ -- downloads/index.json (one record per extension with its version
history, the Extension Hub's own format) and downloads/files/<vid>/<name>.
Importing the Extension Hub's bucket copies its index.json and files/ under
downloads/ unchanged; every id and link carries over.
"""
import io, json, re, secrets, threading, time, zipfile

import imagestore

PREFIX = "downloads/"
INDEX_KEY = PREFIX + "index.json"
MAX_UPLOAD = 100 * 1024 * 1024
ALLOWED = (".zip", ".crx")
_LOCK = threading.Lock()


class DownloadError(Exception):
    """A message that is safe to show."""


def _store():
    return imagestore.store()


def read_index():
    raw = _store().get(INDEX_KEY)
    if not raw:
        return []
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        return []


def _update_index(fn):
    """Read-modify-write under a process lock (one task serves this app)."""
    with _LOCK:
        items = read_index()
        result = fn(items)
        _store().put(INDEX_KEY, json.dumps(items, indent=1).encode("utf-8"), "application/json")
        return result


def safe_name(name):
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", (name or "").replace("\\", "/").rsplit("/", 1)[-1]).strip(" .") or "extension"
    return name[:120]


def _zip_bytes(data):
    """A .crx is a header followed by an ordinary zip; find where the zip starts."""
    if data[:4] == b"Cr24":
        i = data.find(b"PK\x03\x04")
        return data[i:] if i >= 0 else None
    return data if data[:2] == b"PK" else None


def read_manifest(data):
    z = _zip_bytes(data)
    if z is None:
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(z)) as zf:
            # the shallowest manifest.json (zips made from a parent folder nest one level)
            cands = sorted((n for n in zf.namelist() if n.split("/")[-1] == "manifest.json"), key=lambda n: n.count("/"))
            if not cands:
                return {}
            m = json.loads(zf.read(cands[0]).decode("utf-8-sig"))
            return {"name": str(m.get("name", "")), "version": str(m.get("version", "")),
                    "description": str(m.get("description", ""))[:300], "manifest_version": m.get("manifest_version"),
                    "permissions": [str(p) for p in (m.get("permissions") or [])][:40]}
    except (zipfile.BadZipFile, ValueError, KeyError, UnicodeDecodeError):
        return None


def normalize(rec):
    """Entries from before version history: one flat record, turned into the
    versions shape. Their only version keeps the record id, so old links work."""
    if "versions" in rec:
        return rec
    rec = dict(rec)
    rec["versions"] = [{"vid": rec["id"], "file": rec.get("file", ""), "size": rec.get("size", 0),
                        "version": rec.get("version", ""), "uploaded_at": rec.get("uploaded_at", 0),
                        "added_by": rec.get("added_by", ""), "whats_new": ""}]
    rec.setdefault("created_at", rec.get("uploaded_at", 0))
    return rec


def _sync_latest(rec):
    latest = rec["versions"][0]
    for k in ("file", "size", "version", "uploaded_at", "added_by", "whats_new"):
        rec[k] = latest[k]
    return rec


def catalogue():
    items = [normalize(x) for x in read_index()]
    items.sort(key=lambda x: x.get("uploaded_at", 0), reverse=True)
    return {"items": items}


def file_for(vid, name):
    """(bytes, content type, file name) of one version, or None."""
    ver = next((v for x in read_index() for v in normalize(x)["versions"] if v["vid"] == vid), None)
    if not ver or ver["file"] != name:
        return None
    data = _store().get(PREFIX + "files/%s/%s" % (vid, ver["file"]))
    if data is None:
        return None
    ctype = "application/x-chrome-extension" if ver["file"].endswith(".crx") else "application/zip"
    return data, ctype, ver["file"]


def _package(filename, data):
    if not filename or not data:
        raise DownloadError("No file in the upload.")
    name = safe_name(filename)
    if not name.lower().endswith(ALLOWED):
        raise DownloadError("Only .zip and .crx files are accepted.")
    manifest = read_manifest(data)
    if manifest is None:
        raise DownloadError("That file isn't a readable .zip or .crx package.")
    return name, manifest


def add(filename, data, name, description, added_by):
    fname, manifest = _package(filename, data)
    name, description, added_by = (name or "").strip()[:120], (description or "").strip()[:1000], (added_by or "").strip()[:80]
    if not (name and description and added_by):
        raise DownloadError("Name, description and added by are all required.")
    vid = secrets.token_hex(8)
    ver = {"vid": vid, "file": fname, "size": len(data), "version": manifest.get("version", ""),
           "uploaded_at": int(time.time()), "added_by": added_by, "whats_new": ""}
    _store().put(PREFIX + "files/%s/%s" % (vid, fname), data, "application/octet-stream")
    rec = _sync_latest({"id": vid, "name": name, "description": description, "created_at": ver["uploaded_at"],
                        "manifest_version": manifest.get("manifest_version"),
                        "permissions": manifest.get("permissions", []), "versions": [ver]})
    _update_index(lambda items: items.append(rec))
    return rec


def update(ext_id, filename, data, whats_new, added_by):
    fname, manifest = _package(filename, data)
    whats_new, added_by = (whats_new or "").strip()[:2000], (added_by or "").strip()[:80]
    if not (whats_new and added_by):
        raise DownloadError("What's new and added by are both required.")
    if not any(x["id"] == ext_id for x in read_index()):
        raise DownloadError("There's no such extension.")
    vid = secrets.token_hex(8)
    ver = {"vid": vid, "file": fname, "size": len(data), "version": manifest.get("version", ""),
           "uploaded_at": int(time.time()), "added_by": added_by, "whats_new": whats_new}
    _store().put(PREFIX + "files/%s/%s" % (vid, fname), data, "application/octet-stream")

    def add_version(items):
        for i, x in enumerate(items):
            if x["id"] == ext_id:
                rec = normalize(x)
                rec["versions"].insert(0, ver)
                rec["manifest_version"] = manifest.get("manifest_version")
                rec["permissions"] = manifest.get("permissions", [])
                items[i] = _sync_latest(rec)
                return items[i]
        return None
    rec = _update_index(add_version)
    if rec is None:
        raise DownloadError("There's no such extension.")
    return rec


def remove(ext_id):
    """The extension leaves the catalogue; its files stay in the bucket (no delete
    there: a mistaken delete can be undone by putting the record back)."""
    def drop(items):
        rec = next((x for x in items if x["id"] == ext_id), None)
        if rec:
            items.remove(rec)
        return rec
    rec = _update_index(drop)
    if not rec:
        raise DownloadError("There's no such extension.")
    return rec


def parse_multipart(content_type, body):
    from email.parser import BytesParser
    from email.policy import HTTP
    msg = BytesParser(policy=HTTP).parsebytes(b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body)
    fields = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if name:
            fields[name] = (part.get_filename(), part.get_payload(decode=True) or b"")
    return fields
