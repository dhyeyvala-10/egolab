"""
`make seed`: sample data made by real processing, never inserted rows.

Builds clips from MediaPipe's test photos (see egolabs.cv.samples) — hands on their own, and a hand reaching
for, grasping, carrying, pressing, and tapping an object — uploads them through the public API exactly as
the browser does, waits for ingest, then runs hand tracking and object detection with the configured
adapters, and movement classification on their output. Everything it creates is labelled as seed data (file
names start with `seed-`, in one session whose task says it came from `make seed`).

    python -m egolabs.seed --api http://localhost:8000 --token "$(python -m egolabs.token you@gmail.com)"

(or `--email … --password …` for a password account, when the API runs with PASSWORD_LOGIN=true).
"""

import argparse
import sys
import tempfile
import time
from pathlib import Path

import httpx

from egolabs.cv import samples

CLIPS: dict[str, list[samples.Segment | int]] = {
    "seed-hands-pointing-victory-thumb.mp4": [
        samples.Segment("pointing_up.jpg", 90, start=(0.3, 0.5), end=(0.45, 0.55)),
        15,
        samples.Segment("victory.jpg", 90, start=(0.72, 0.5), end=(0.58, 0.45)),
        samples.Segment("thumb_up.jpg", 90, start=(0.3, 0.45), end=(0.5, 0.5), zoom=0.15),
    ],
    "seed-two-right-hands.mp4": [
        samples.Segment("right_hands.jpg", 150, height=0.55, start=(0.4, 0.5), end=(0.6, 0.55))
    ],
    "seed-pinch-swipe-rotate.mp4": samples.GESTURE_SEGMENTS,
}

SCENES: dict[str, list[samples.SceneSegment]] = {
    "seed-hand-object-grasp.mp4": samples.grasp_scene(),
    "seed-hand-object-press-tap.mp4": samples.press_and_tap_scene(),
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument(
        "--token", help="an access token for an admin, annotator, or reviewer (egolabs.token)"
    )
    parser.add_argument("--email", help="or a password account's email (API with PASSWORD_LOGIN=true)")
    parser.add_argument("--password")
    args = parser.parse_args()
    api = f"{args.api.rstrip('/')}/api/v1"
    client = httpx.Client(timeout=120)

    if args.token:
        token = args.token.strip()
    elif args.email and args.password:
        login = client.post(f"{api}/auth/login", json={"email": args.email, "password": args.password})
        if login.status_code != 200:
            print(f"Sign-in failed ({login.status_code}): {login.text}", file=sys.stderr)
            return 1
        token = login.json()["access_token"]
    else:
        parser.error("give --token, or --email and --password")
    auth = {"Authorization": f"Bearer {token}"}
    me = client.get(f"{api}/auth/me", headers=auth)
    if me.status_code != 200:
        print(f"The token wasn't accepted ({me.status_code}): {me.text}", file=sys.stderr)
        return 1

    session = client.post(
        f"{api}/sessions",
        json={"task": "Seed data (make seed)", "environment": "synthetic",
              "notes": "Sample clips built from MediaPipe's published test photos by `make seed`, processed for real."},
        headers=auth,
    )  # fmt: skip
    session.raise_for_status()
    session_id = session.json()["id"]
    print(f"session {session.json()['name']}")

    video_ids = []
    with tempfile.TemporaryDirectory() as tmp:
        clips = [(n, lambda p, s=s: samples.make_clip(p, s).path) for n, s in CLIPS.items()]
        clips += [(n, lambda p, s=s: samples.make_scene_clip(p, s).path) for n, s in SCENES.items()]
        for name, render in clips:
            path = render(Path(tmp) / name)
            data = path.read_bytes()
            up = client.post(
                f"{api}/uploads",
                json={"filename": name, "size_bytes": len(data), "session_id": session_id},
                headers=auth,
            )
            up.raise_for_status()
            upload = up.json()
            numbers = list(range(1, upload["part_count"] + 1))
            urls = client.post(
                f"{api}/uploads/{upload['id']}/parts", json={"part_numbers": numbers}, headers=auth
            ).json()
            parts = []
            for u in urls["urls"]:
                n = u["part_number"]
                res = httpx.put(
                    u["url"],
                    content=data[(n - 1) * upload["part_size"] : n * upload["part_size"]],
                    timeout=300,
                )
                res.raise_for_status()
                parts.append({"part_number": n, "etag": res.headers["etag"]})
            client.post(
                f"{api}/uploads/{upload['id']}/complete", json={"parts": parts}, headers=auth
            ).raise_for_status()
            print(f"uploaded {name}")
            video_ids.append(_wait_for_video(client, api, auth, upload["id"]))

    # Default kinds: hand tracking + object detection, then movement classification on both.
    runs = client.post(f"{api}/cv/runs", json={"video_ids": video_ids}, headers=auth)
    runs.raise_for_status()
    web = args.api.rstrip("/").replace(":8000", ":3000")
    pages = {"hand_tracking": "cv/hands", "object_detection": "cv/objects", "movement": "cv/movements/runs"}
    for run in runs.json():
        final = _wait(
            client, f"{api}/cv/runs/{run['id']}", auth, lambda r: r["status"] in ("succeeded", "failed"), 1800
        )
        mv = final["model_version"]
        count = (
            f"{final['detections']} events" if final["kind"] == "movement" else f"{final['tracks']} tracks"
        )
        print(
            f"{final['video']['name']} · {final['kind']}: {final['status']}, {count}, model {mv['name'] if mv else '—'}"
        )
        print(f"  {web}/{pages[final['kind']]}/{run['id']}")
    print(f"Movement events: {web}/cv/movements")
    return 0


def _wait(client: httpx.Client, url: str, auth: dict, done, timeout: float = 900):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(url, headers=auth).json()
        if done(body):
            return body
        time.sleep(2)
    raise TimeoutError(url)


def _wait_for_video(client: httpx.Client, api: str, auth: dict, upload_id: str) -> str:
    upload = _wait(
        client, f"{api}/uploads/{upload_id}", auth, lambda u: u["status"] not in ("uploading", "processing")
    )
    if not upload.get("video_id"):
        raise RuntimeError(f"upload ended as {upload['status']}: {upload.get('error')}")
    _wait(client, f"{api}/videos/{upload['video_id']}", auth, lambda v: v["status"] in ("ready", "corrupt"))
    return upload["video_id"]


if __name__ == "__main__":
    raise SystemExit(main())
