import http.cookiejar
import json
import time
import urllib.request
from pathlib import Path
import uuid

BASE = "http://127.0.0.1:8791"
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

def post_json(path, data):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with opener.open(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

def put_json(path, data):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="PUT"
    )
    with opener.open(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

def get_json(path):
    with opener.open(BASE + path, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

def upload_file(path, filename="image.png"):
    boundary = "----WebKitFormBoundary" + uuid.uuid4().hex
    content = Path(path).read_bytes()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        BASE + "/api/assets",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    with opener.open(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

print("1. Logging in...")
post_json("/api/login", {"password": "demo123"})
cfg = get_json("/api/config")
print("Config:", cfg)
assert cfg["mode"] == "live"
assert cfg["generation_ready"] is True

print("2. Uploading assets...")
sample_bag = Path("evidence/samples/bag.png")
asset_main = upload_file(sample_bag, "main_bag.png")
print("Main asset:", asset_main["id"])
asset_ref = upload_file(sample_bag, "ref_bag.png")
print("Ref asset:", asset_ref["id"])

print("3. Testing SAM segmentation prepare & select on ref asset...")
prep_res = post_json("/api/segmentation/prepare", {"image_id": asset_ref["id"]})
print("SAM prepare:", prep_res)

sel_res = post_json("/api/segmentation/select", {"image_id": asset_ref["id"], "x": 0.5, "y": 0.5})
print("SAM select candidates count:", len(sel_res.get("candidates", [])))
assert len(sel_res.get("candidates", [])) > 0
candidate_mask = sel_res["candidates"][0]

print("4. Creating target mask on main asset...")
target_mask = post_json("/api/masks", {
    "image_id": asset_main["id"],
    "points": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]
})
print("Target mask id:", target_mask["id"])

print("5. Initializing draft...")
draft = post_json("/api/drafts", {})
draft_id = draft["id"]
print("Created draft:", draft_id)

draft_state = {
    "id": draft_id,
    "revision": draft["revision"],
    "schema_version": 2,
    "name": "Live Image2.5 Verification",
    "main_image": asset_main["id"],
    "references": [asset_ref["id"]],
    "full_image_refs": [],
    "next_display_index": 2,
    "mappings": [
        {
            "id": uuid.uuid4().hex,
            "display_index": 1,
            "color": "#8b5cf6",
            "mode": "replace",
            "source": {
                "image_id": asset_ref["id"],
                "image_version": 1,
                "mask_id": candidate_mask["id"],
                "anchor": {"x": 0.5, "y": 0.5},
                "label": "黑色皮包",
                "strategy": "context-crop"
            },
            "target": {
                "image_id": asset_main["id"],
                "image_version": 1,
                "mask_id": target_mask["id"],
                "edit_region_id": target_mask["id"],
                "anchor": {"x": 0.5, "y": 0.5}
            },
            "requirement": "保持黑色皮包主体与细节，置于极简米白色大理石摄影台上，背景柔和暖光"
        }
    ],
    "instructions": "精细电商产品静物摄影，4K画质，真实光影质感，无水印无文字"
}

put_resp = put_json(f"/api/drafts/{draft_id}", draft_state)
print("Draft saved revision:", put_resp["revision"])

val_res = post_json("/api/validate", draft_state)
print("Validate result:", val_res)

job_key = "live-verify-" + uuid.uuid4().hex[:12]
print(f"Submitting job with idempotency key {job_key}...")
job_resp = post_json("/api/jobs", {
    "draft_id": draft_id,
    "revision": put_resp["revision"],
    "idempotency_key": job_key
})
print("Job submitted:", job_resp)
jid = job_resp["id"]

print("6. Polling job execution status...")
start_time = time.time()
while time.time() - start_time < 300:
    time.sleep(3)
    curr_job = get_json(f"/api/jobs/{jid}")
    st = curr_job.get("status")
    print(f"[{round(time.time() - start_time, 1)}s] Job {jid} status: {st}")
    if st in ("succeeded", "failed", "simulated", "save_failed", "unknown"):
        break

print("Final job state:", json.dumps(curr_job, ensure_ascii=False, indent=2))
assert curr_job["status"] == "succeeded", f"Job failed with status: {curr_job['status']}"

res_assets = curr_job.get("result", {}).get("assets", [])
print(f"Generated assets count: {len(res_assets)}")
assert len(res_assets) > 0

out_path = Path("D:/image-editor-development/diagnostics/live-user-flow-result.png")
with opener.open(f"{BASE}/api/assets/{res_assets[0]}") as resp:
    out_path.write_bytes(resp.read())
print(f"Saved generated image to {out_path}, size: {out_path.stat().st_size} bytes")

print("7. Verifying server remains fully healthy and responsive...")
health = get_json("/api/health")
print("Health:", health)
print("ALL VERIFICATIONS COMPLETED SUCCESSFULLY!")
