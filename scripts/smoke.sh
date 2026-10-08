#!/usr/bin/env bash
# End-to-end check of a running stack (Phase 0 and Phase 1 acceptance):
#   API healthy → register → log in → overview → worker runs a job → direct-to-storage upload, duplicate
#   and corrupt handling, proxy playback → web serves sign-in and guards the shell.
# Usage: scripts/smoke.sh   (API_URL and WEB_URL default to the docker compose ports)
# People sign in with Google; this script uses the API's password sign-in, so start the stack with
# PASSWORD_LOGIN=true (CI does).
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
WEB_URL="${WEB_URL:-http://localhost:3000}"
EMAIL="smoke-$(date +%s)-$RANDOM@example.com"
PASSWORD="smoke-test-password"

json() { python3 -c "import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1], {'d': d}))" "$1"; }
fail() { echo "FAIL: $*" >&2; exit 1; }
step() { echo "--- $*"; }

step "API health"
for _ in $(seq 1 60); do
  status=$(curl -fsS "$API_URL/api/v1/health" 2>/dev/null | json 'd["status"]' || true)
  [ "$status" = "ok" ] && break
  sleep 2
done
[ "$status" = "ok" ] || { curl -sS "$API_URL/api/v1/health" || true; fail "API not healthy (status: ${status:-none})"; }

step "Google sign-in is offered"
google=$(curl -fsS "$API_URL/api/v1/auth/google")
echo "google sign-in set up: $(echo "$google" | json 'd["enabled"]')"
echo "$google" | grep -q '"authorize_url"' || fail "GET /auth/google didn't describe Google sign-in"

step "Register $EMAIL"
code=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/v1/auth/register" -H 'content-type: application/json' -d '{}')
[ "$code" != "404" ] || fail "password sign-in is off: start the stack with PASSWORD_LOGIN=true for the smoke test"
reg=$(curl -fsS -X POST "$API_URL/api/v1/auth/register" -H 'content-type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\",\"name\":\"Smoke Test\"}")
role=$(echo "$reg" | json 'd["user"]["role"]')
echo "role: $role"

step "Log in"
token=$(curl -fsS -X POST "$API_URL/api/v1/auth/login" -H 'content-type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" | json 'd["access_token"]')
auth=(-H "Authorization: Bearer $token")
[ "$(curl -fsS "${auth[@]}" "$API_URL/api/v1/auth/me" | json 'd["email"]')" = "$EMAIL" ] || fail "/auth/me returned another user"

step "Overview"
curl -fsS "${auth[@]}" "$API_URL/api/v1/overview" | json 'd["counts"]'

if [ "$role" = "admin" ]; then
  step "Worker runs a system.healthcheck job"
  job_id=$(curl -fsS -X POST "${auth[@]}" "$API_URL/api/v1/jobs/healthcheck" | json 'd["id"]')
  for _ in $(seq 1 60); do
    job_status=$(curl -fsS "${auth[@]}" "$API_URL/api/v1/jobs/$job_id" | json 'd["status"]')
    case "$job_status" in succeeded|failed) break ;; esac
    sleep 1
  done
  curl -fsS "${auth[@]}" "$API_URL/api/v1/jobs/$job_id/logs" | json '[l["level"] + ": " + l["message"] for l in d["items"]]'
  [ "$job_status" = "succeeded" ] || fail "healthcheck job ended as '$job_status'"
  curl -fsS "${auth[@]}" "$API_URL/api/v1/jobs/$job_id" | json 'd["result"]'
else
  echo "(skipping worker check: $EMAIL is not the first user, so not an admin)"
fi

if [ "$role" = "admin" ]; then
  step "Ingest: upload a video straight to storage, then the same file again, then a corrupt file"
  work=$(mktemp -d)
  trap 'rm -rf "$work"' EXIT
  make_clip() {  # ffmpeg on the host if present, else inside the api container
    local args=(-v error -f lavfi -i testsrc=size=320x240:rate=30 -t 2 -c:v libx264 -pix_fmt yuv420p
                -movflags frag_keyframe+empty_moov -f mp4 pipe:1)
    if command -v ffmpeg >/dev/null; then ffmpeg "${args[@]}" > "$1"
    else docker compose exec -T api ffmpeg "${args[@]}" > "$1"; fi
  }
  make_clip "$work/smoke.mp4"
  head -c 200000 /dev/urandom > "$work/broken.mp4"

  upload() {  # $1 file, $2 name → prints upload id once ingested
    local size id url etag
    size=$(wc -c < "$1" | tr -d ' ')
    id=$(curl -fsS -X POST "${auth[@]}" -H 'content-type: application/json' "$API_URL/api/v1/uploads" \
      -d "{\"filename\":\"$2\",\"size_bytes\":$size}" | json 'd["id"]')
    url=$(curl -fsS -X POST "${auth[@]}" -H 'content-type: application/json' "$API_URL/api/v1/uploads/$id/parts" \
      -d '{"part_numbers":[1]}' | json 'd["urls"][0]["url"]')
    etag=$(curl -fsS -X PUT --data-binary "@$1" -D - -o /dev/null "$url" | tr -d '\r' | awk -F': ' 'tolower($1)=="etag"{print $2}')
    [ -n "$etag" ] || fail "storage returned no ETag for the part upload"
    curl -fsS -X POST "${auth[@]}" -H 'content-type: application/json' "$API_URL/api/v1/uploads/$id/complete" \
      -d "{\"parts\":[{\"part_number\":1,\"etag\":$(printf '%s' "$etag" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}]}" >/dev/null
    for _ in $(seq 1 90); do
      state=$(curl -fsS "${auth[@]}" "$API_URL/api/v1/uploads/$id" | json 'd["status"]')
      [ "$state" != "processing" ] && break
      sleep 1
    done
    echo "$id"
  }
  field() { curl -fsS "${auth[@]}" "$API_URL/api/v1/uploads/$1" | json "$2"; }

  first=$(upload "$work/smoke.mp4" smoke.mp4)
  [ "$(field "$first" 'd["status"]')" = "processed" ] || fail "first upload ended as $(field "$first" 'd["status"]')"
  video=$(field "$first" 'd["video_id"]')
  second=$(upload "$work/smoke.mp4" smoke-again.mp4)
  [ "$(field "$second" 'd["status"]')" = "duplicate" ] || fail "re-upload was not detected as a duplicate"
  [ "$(field "$second" 'd["video_id"]')" = "$video" ] || fail "duplicate not linked to the existing video"
  echo "same file twice → one video ($video)"

  bad=$(upload "$work/broken.mp4" broken.mp4)
  bad_video=$(field "$bad" 'd["video_id"]')
  [ "$(curl -fsS "${auth[@]}" "$API_URL/api/v1/videos/$bad_video" | json 'd["status"]')" = "corrupt" ] || fail "corrupt file not flagged"
  echo "corrupt file flagged (upload $(field "$bad" 'd["status"]'))"

  for _ in $(seq 1 90); do
    vstatus=$(curl -fsS "${auth[@]}" "$API_URL/api/v1/videos/$video" | json 'd["status"]')
    [ "$vstatus" = "ready" ] && break
    sleep 1
  done
  [ "$vstatus" = "ready" ] || fail "video never became ready (status: $vstatus)"
  curl -fsS "${auth[@]}" "$API_URL/api/v1/videos/$video" | json '{k: d[k] for k in ("width","height","fps","frame_count","codec")}'
  proxy=$(curl -fsS "${auth[@]}" "$API_URL/api/v1/videos/$video" | json 'd["proxy_url"]')
  [ "$(curl -sS -o /dev/null -w '%{http_code}' -r 0-1023 "$proxy")" = "206" ] || fail "proxy not playable from storage"
  echo "proxy served from storage"

  step "Inspector and annotation (Phase 2)"
  frames=$(curl -fsS "${auth[@]}" "$API_URL/api/v1/videos/$video" | json 'd["frame_count"]')
  indexed=$(curl -fsS "${auth[@]}" "$API_URL/api/v1/videos/$video/frame-index" | json 'd["frame_count"]')
  [ "$indexed" = "$frames" ] || fail "frame index has $indexed frames, video has $frames"
  echo "frame index covers all $frames frames"
  ann=$(curl -fsS -X POST "${auth[@]}" -H 'content-type: application/json' "$API_URL/api/v1/videos/$video/annotations" \
    -d '{"type":"segment","label":"smoke","frame_start":0,"frame_end":10}' | json 'd["id"]')
  curl -fsS -X DELETE "${auth[@]}" "$API_URL/api/v1/annotations/$ann" >/dev/null
  actions=$(curl -fsS "${auth[@]}" "$API_URL/api/v1/annotations/$ann/history" | json '",".join(r["action"] for r in d["revisions"])')
  [ "$actions" = "created,deleted" ] || fail "annotation history after delete was '$actions'"
  tracks=$(curl -fsS "${auth[@]}" "$API_URL/api/v1/videos/$video/timeline" | json 'len(d["tracks"])')
  [ "$tracks" = "7" ] || fail "timeline returned $tracks tracks"
  echo "deleted annotation kept in history; timeline has all 7 tracks"

  step "Hand tracking, object detection, movement classification (Phases 3–4)"
  runs=$(curl -fsS -X POST "${auth[@]}" -H 'content-type: application/json' "$API_URL/api/v1/cv/runs" \
    -d "{\"video_ids\":[\"$video\"]}" | json '" ".join(r["kind"] + "=" + r["id"] for r in d)')
  echo "queued: $runs"
  for pair in $runs; do
    kind=${pair%%=*}; run=${pair#*=}
    for _ in $(seq 1 180); do
      rstatus=$(curl -fsS "${auth[@]}" "$API_URL/api/v1/cv/runs/$run" | json 'd["status"]')
      case "$rstatus" in succeeded|failed) break ;; esac
      sleep 1
    done
    [ "$rstatus" = "succeeded" ] || fail "$kind run ended as $rstatus: $(curl -fsS "${auth[@]}" "$API_URL/api/v1/cv/runs/$run" | json 'd["error"]')"
    curl -fsS "${auth[@]}" "$API_URL/api/v1/cv/runs/$run" | json '{"kind": d["kind"], "frames": d["frames_processed"], "tracks": d["tracks"], "detections": d["detections"], "model": d["model_version"]["name"] + " " + d["model_version"]["version"], "inputs": d["inputs"]}'
  done
  [ "$(echo "$runs" | wc -w)" = "3" ] || fail "expected hand, object, and movement runs, got: $runs"
  phases=$(curl -fsS "${auth[@]}" "$API_URL/api/v1/videos/$video/timeline" | json '",".join(str(t["filled_from_phase"]) for t in d["tracks"] if t["id"] in ("object", "movement"))')
  [ "$phases" = "None,None" ] || fail "object/movement timeline tracks not filled: $phases"
  classes=$(curl -fsS "${auth[@]}" "$API_URL/api/v1/movement/classes" | json 'len(d)')
  [ "$classes" -ge 20 ] || fail "only $classes movement classes"
  echo "worker ran the configured hand, object, and movement adapters, chained; $classes movement classes"

  step "Review and active learning (Phase 5)"
  summary=$(curl -fsS "${auth[@]}" "$API_URL/api/v1/review/summary?video_id=$video" | json 'd["totals"]["total"]')
  queued=$(curl -fsS "${auth[@]}" "$API_URL/api/v1/review/queue?video_id=$video&limit=1" | json 'd["total"]')
  echo "review summary counts $summary predictions; $queued waiting in the queue"
  if [ "$queued" -gt 0 ]; then
    first=$(curl -fsS "${auth[@]}" "$API_URL/api/v1/review/queue?video_id=$video&limit=1" | json 'd["items"][0]["id"]')
    other=$(curl -fsS "${auth[@]}" "$API_URL/api/v1/review/queue?video_id=$video&limit=1" | json '"tap" if d["items"][0]["movement_class"]["name"] == "gesture" else "gesture"')
    fixed=$(curl -fsS -X POST "${auth[@]}" -H 'content-type: application/json' "$API_URL/api/v1/review/events/$first/correct" \
      -d "{\"class\":\"$other\"}" | json 'd["parent_event_id"] + " " + d["event"]["source"]')
    [ "$fixed" = "$first auto_corrected" ] || fail "correction wasn't a new version of $first: $fixed"
    old=$(curl -fsS "${auth[@]}" "$API_URL/api/v1/movement/events/$first" | json 'd["status"]')
    [ "$old" = "corrected" ] || fail "corrected prediction is '$old'"
    echo "correction stored as a new version; the prediction is kept (corrected)"
  fi

  step "Dataset version, rebuild check, export, lineage (Phase 6)"
  wait_for() {  # $1 url, $2 python expression that is true once done → prints the final body
    local body
    for _ in $(seq 1 180); do
      body=$(curl -fsS "${auth[@]}" "$1")
      [ "$(echo "$body" | json "$2")" = "True" ] && { echo "$body"; return; }
      sleep 1
    done
    fail "timed out waiting for $1: $body"
  }
  ds=$(curl -fsS -X POST "${auth[@]}" -H 'content-type: application/json' "$API_URL/api/v1/datasets" \
    -d "{\"name\":\"smoke-$(date +%s)-$RANDOM\"}" | json 'd["id"]')
  version=$(curl -fsS -X POST "${auth[@]}" -H 'content-type: application/json' "$API_URL/api/v1/datasets/$ds/versions" \
    -d "{\"spec\":{\"filters\":{\"video_ids\":[\"$video\"],\"statuses\":[\"auto_detected\",\"needs_review\",\"confirmed\"]}}}" | json 'd["id"]')
  built=$(wait_for "$API_URL/api/v1/datasets/versions/$version" 'd["status"] != "building"')
  [ "$(echo "$built" | json 'd["status"]')" = "ready" ] || fail "version build ended as: $(echo "$built" | json 'd["status"] + " " + str(d["error"])')"
  hash=$(echo "$built" | json 'd["content_hash"]')
  samples=$(echo "$built" | json 'd["sample_count"]')
  echo "version built: $samples samples, hash $hash"
  curl -fsS -X POST "${auth[@]}" "$API_URL/api/v1/datasets/versions/$version/checks" >/dev/null
  check=$(wait_for "$API_URL/api/v1/datasets/versions/$version/checks" 'd[0]["status"] != "building"')
  [ "$(echo "$check" | json 'd[0]["matches"] and d[0]["content_hash"]')" = "$hash" ] || fail "rebuild from the recorded spec didn't match: $check"
  echo "rebuilt from its recorded spec: identical hash"
  export_id=$(curl -fsS -X POST "${auth[@]}" -H 'content-type: application/json' "$API_URL/api/v1/datasets/versions/$version/exports" \
    -d '{"format":"jsonl"}' | json 'd["id"]')
  exported=$(wait_for "$API_URL/api/v1/datasets/exports?version_id=$version" 'd["items"][0]["status"] != "building"')
  [ "$(echo "$exported" | json 'd["items"][0]["status"]')" = "ready" ] || fail "export ended as: $(echo "$exported" | json 'd["items"][0]["error"]')"
  curl -fsS -o "$work/export.zip" "$(curl -fsS "${auth[@]}" "$API_URL/api/v1/datasets/exports/$export_id/download" | json 'd["url"]')"
  got=$(python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$work/export.zip")
  [ "$got" = "$(echo "$exported" | json 'd["items"][0]["sha256"]')" ] || fail "downloaded export doesn't match its recorded sha256"
  echo "JSON Lines export downloaded from storage; sha256 matches"
  if [ "$samples" -gt 0 ]; then
    sample=$(curl -fsS "${auth[@]}" "$API_URL/api/v1/datasets/versions/$version/samples?limit=1" | json 'd["items"][0]["id"]')
    [ "$(curl -fsS "${auth[@]}" "$API_URL/api/v1/datasets/samples/$sample/lineage" | json 'd["reaches_raw_file"]')" = "True" ] || fail "sample $sample doesn't trace to a raw file"
    echo "lineage reaches the raw file"
  fi

  step "Pipeline run, searchable logs, annotated video (Phase 7)"
  graph='{"nodes":[{"id":"ingest","type":"ingest","config":{"verify_checksum":true}},{"id":"frames","type":"extract_frames"},{"id":"blur","type":"quality_blur"},{"id":"render","type":"render_video"}],"edges":[{"from":"ingest","to":"frames"},{"from":"frames","to":"blur"},{"from":"frames","to":"render"}]}'
  pipeline=$(curl -fsS -X POST "${auth[@]}" -H 'content-type: application/json' "$API_URL/api/v1/pipelines" \
    -d "{\"name\":\"smoke-$(date +%s)-$RANDOM\",\"graph\":$graph}" | json 'd["id"]')
  run=$(curl -fsS -X POST "${auth[@]}" -H 'content-type: application/json' "$API_URL/api/v1/pipelines/$pipeline/runs" \
    -d "{\"inputs\":{\"video_ids\":[\"$video\"]}}" | json 'd["id"]')
  finished=$(wait_for "$API_URL/api/v1/pipelines/runs/$run" 'd["status"] != "running"')
  if [ "$(echo "$finished" | json 'd["status"]')" != "succeeded" ]; then
    curl -fsS "${auth[@]}" "$API_URL/api/v1/pipelines/runs/$run/steps" | json '[(s["label"], s["status"], s["error"]) for s in d["items"]]'
    fail "pipeline run ended as $(echo "$finished" | json 'd["status"]')"
  fi
  echo "run succeeded: $(echo "$finished" | json 'd["counts"]')"
  total=$(curl -fsS "${auth[@]}" "$API_URL/api/v1/pipelines/runs/$run/logs?limit=1" | json 'd["total"]')
  found=$(curl -fsS "${auth[@]}" -G "$API_URL/api/v1/pipelines/runs/$run/logs" --data-urlencode "q=Checksum matches" | json 'd["matched"]')
  [ "$found" -ge 1 ] || fail "log search found no 'Checksum matches' line"
  lines=$(curl -fsS "${auth[@]}" "$API_URL/api/v1/pipelines/runs/$run/logs.txt" | wc -l | tr -d ' ')
  [ "$lines" = "$total" ] || fail "logs.txt has $lines lines, the run $total"
  echo "run log: $total lines, searchable, downloadable"
  annotated=$(curl -fsS "${auth[@]}" "$API_URL/api/v1/videos/$video/annotated" | json 'd[0]["id"] if d and d[0]["status"] == "ready" else ""')
  [ -n "$annotated" ] || fail "no annotated video was rendered"
  expected=$(curl -fsS "${auth[@]}" "$API_URL/api/v1/videos/$video/annotated" | json 'd[0]["sha256"]')
  curl -fsS -o "$work/annotated.mp4" "$(curl -fsS "${auth[@]}" "$API_URL/api/v1/annotated-videos/$annotated/download" | json 'd["url"]')"
  got=$(python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$work/annotated.mp4")
  [ "$got" = "$expected" ] || fail "downloaded annotated video doesn't match its sha256"
  echo "annotated video rendered and downloaded"
fi

step "Web"
code=$(curl -sS -o /dev/null -w '%{http_code}' "$WEB_URL/login")
[ "$code" = "200" ] || fail "GET /login returned $code"
curl -fsS "$WEB_URL/login" | grep -q "Continue with Google" || fail "the login page doesn't offer Google sign-in"
code=$(curl -sS -o /dev/null -w '%{http_code}' "$WEB_URL/")
[ "$code" = "200" ] || fail "GET / (the public landing page) returned $code"
location=$(curl -sS -o /dev/null -w '%{redirect_url}' "$WEB_URL/data/videos")
case "$location" in *"/login?next=%2Fdata%2Fvideos"*) ;; *) fail "signed-out visit to /data/videos redirected to '$location'" ;; esac

echo "OK: stack passed the smoke test (Phases 0–7: foundation, ingestion, annotation, hand tracking, movement, review, datasets, pipelines)"
