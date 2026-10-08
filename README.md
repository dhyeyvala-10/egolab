# Ego Labs

An operating system for ingesting, processing, annotating, versioning, and exporting egocentric video data for robotics and ML training.

**Pipeline:** Raw Video → Ingestion → Processing → Hand/Finger Tracking → Movement Detection → Human Annotation → Dataset Versioning → Export → Evaluation & Monitoring

The full plan is in [`docs/ego-labs-phased-spec.md`](docs/ego-labs-phased-spec.md). Current status is in [`PROGRESS.md`](PROGRESS.md).

## Quick start

```bash
cp .env.example .env                  # then set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET (below)
docker compose up -d --build --wait   # or: make up
open http://localhost:3000            # "Continue with Google": OWNER_EMAIL (else the first account) is admin
PASSWORD_LOGIN=true make up && make smoke   # optional end-to-end check (it signs in with a password)
```

The stack keeps itself running: every service restarts if it stops, and comes back when Docker starts
(unless you ran `docker compose stop` or `down`). To have it start when your computer does, turn on Docker
Desktop → Settings → General → **Start Docker Desktop when you sign in**.

**Process every upload by itself:** in the Pipeline Builder, open a pipeline (for example one made from the
"Process videos" template), tick **Run automatically on new uploads**, and save. From then on, each uploaded
video runs through it as soon as its upload checks finish; the runs appear under Pipelines → Runs as "New upload".

**Putting it online:** [`docs/deploy.md`](docs/deploy.md) runs it on a Windows machine at home or in the office,
reachable at your own domain with HTTPS through a Cloudflare Tunnel (no router changes): `docker-compose.prod.yml`
plus `scripts/deploy.ps1` (checks `.env`, updates, starts) and `scripts/backup.ps1`.

### Sign-in with Google

People sign in with their Google account; there is one login page and no passwords. Signing in the first
time creates the account, named and emailed from Google. The owners (`OWNER_EMAIL` in `.env`: one or more
emails separated by commas, else the first account) are the admins, and nobody can change them from the app.
Everyone else starts with **no access**: they see a "Waiting for access" page until an owner gives them a role
in **Settings → Users**.

The owner's controls, all under **Settings**:

- **Users:** give each person a role (viewer, annotator, reviewer) or take access away; block an account;
  see who is online, when each person joined and last signed in.
- **Requests:** an upload over the size limit waits here before any of it is sent; a video over the length
  limit is stored but nothing processes it until the owner allows it. Allow or reject each one.
- **Limits:** the size limit (1 GB out of the box), the length limit (none out of the box), and who may start
  processing (pipelines, their runs and schedules, tracking runs, auto annotation, dataset versions and
  exports): only the owner (out of the box), or annotators and reviewers too. The owner is never held back.
- **Activity:** every sign-in with its browser and address, and everything everyone did.

People see only their own uploads and their own activity on the dashboard; the owner sees everyone's, with
who sent each upload, how much of it has arrived, whether it has stopped moving, and a Cancel button.

To set it up once:

1. In [Google Cloud Console](https://console.cloud.google.com/apis/credentials), pick or create a project and
   configure the OAuth consent screen (app name, your support email; "External" lets any Google account
   sign in).
2. **Create credentials → OAuth client ID → Web application.** Under **Authorised redirect URIs** add
   `http://localhost:3000/auth/google/callback` (and `https://<your web address>/auth/google/callback` for a
   deployment).
3. Put the client ID and secret in `.env` as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, and restart the
   stack. Behind a proxy or load balancer, also set `PUBLIC_WEB_URL` to the address people use.

Until then the login page says Google sign-in isn't set up. `PASSWORD_LOGIN=true` turns on the API's email
and password sign-in for scripts (the smoke test); it never appears on the login page.

| Service | URL | Notes |
| --- | --- | --- |
| Web | http://localhost:3000 | Next.js app |
| API | http://localhost:8000/api/v1 | FastAPI; OpenAPI at `/api/v1/openapi.json`, docs at `/docs` |
| MinIO | http://localhost:9001 | Object storage console (`egolabs` / `egolabs-dev-secret`) |
| Postgres | localhost:5432 | `egolabs` / `egolabs` |
| Redis | localhost:6379 | Celery broker |

The first `docker compose up` compiles MinIO from a pinned source release (`infra/minio/Dockerfile`; MinIO no longer publishes container images), which takes a few minutes. Later starts reuse the built image.

Every setting has a development default. Override any of them in a root `.env` (see `.env.example`); set a real `JWT_SECRET` and `ENVIRONMENT=production` anywhere that isn't a laptop.

## Repository layout

| Path | What it is |
| --- | --- |
| `backend/` | FastAPI API, SQLAlchemy models, Alembic migrations, Celery worker (`egolabs` package). |
| `web/` | Ego Labs web app (Next.js App Router + TypeScript + Tailwind). |
| `docker-compose.yml` | Postgres, Redis, MinIO, API, worker, scheduler, web. |
| `infra/minio/` | MinIO image built from a pinned source release. |
| `scripts/smoke.sh` | End-to-end check of a running stack: health, sign-in, a worker job, then one clip through every built phase (ingest → annotation → tracking → movement → review → dataset version, rebuild check, export → a pipeline run with its logs and an annotated video) and the web. |
| `docs/` | The phased build spec. |
| `PROGRESS.md` | Per-phase checklists and acceptance evidence. |

## Progress

`PROGRESS.md` holds the per-phase checklists and the evidence for each acceptance criterion; it is updated at the end of every phase. The current plan is Phases 0–7. In the app, the dashboard shows each pipeline level as live or in progress, from the pages built so far.

## Backend

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # or: make setup
docker compose up -d postgres redis minio                      # dependencies only
.venv/bin/python -m egolabs.bootstrap                           # migrations + buckets
.venv/bin/uvicorn egolabs.app:app --reload                      # API on :8000
.venv/bin/celery -A egolabs.worker.celery_app worker -l INFO    # worker
.venv/bin/celery -A egolabs.worker.celery_app beat -l INFO      # scheduler (pipeline schedules, retries)
```

- **Schema:** `egolabs/models/` holds the full Phase 0 core schema: users, datasets, sessions, videos, frames (indexed lazily, never one row per frame), devices, operators, jobs, job_logs, model_versions, annotations, events, lineage_edges. The database enforces the product principles with CHECK constraints — e.g. an `auto` annotation must carry a confidence and a model version, and a correction must point at its original.
- **Migrations:** Alembic, in `alembic/versions/`. After changing models: `make migration m="describe the change"`.
- **Auth:** sign-in with Google (OpenID Connect, authorization code flow with PKCE), then JWT bearer tokens. `GET /api/v1/auth/google` tells the web app whether it's set up; `POST /api/v1/auth/google` takes the code from Google's redirect, exchanges it at Google's token endpoint with the client secret, and verifies the ID token (RS256 against Google's published keys, audience, issuer, expiry, verified email). The account is found by Google's id, else linked by email, else created. Roles: `admin` (the owners only: `OWNER_EMAIL`, comma-separated, else the first account), `annotator`, `reviewer`, `viewer`, and `pending` (signed in, no access: every API call but `/auth/me` answers 403). The owner changes roles with `PATCH /api/v1/users/{id}`; nobody can be made admin and owners can't be changed from the app. Every sign-in is kept (`GET /api/v1/users/sign-ins`) and every action is listed with who did it (`GET /api/v1/users/activity`). Limits live in `app_settings` (`GET`/`PATCH /api/v1/settings/limits`); what waits for the owner is `GET /api/v1/requests`, answered with `POST /api/v1/uploads/{id}/approve|reject` and `POST /api/v1/requests/videos/{id}/allow|reject`. Email and password sign-in (`/auth/register`, `/auth/login`, Argon2id) answers only with `PASSWORD_LOGIN=true`, for scripts; `python -m egolabs.token you@gmail.com` prints a token for an existing account.
- **Jobs:** every job is a `jobs` row; the Celery task only carries its id. Handlers register with `@job_handler("type")` and write structured `job_logs` lines. `POST /api/v1/jobs/healthcheck` (admin) queues a job that checks the worker can reach the database, Redis, and storage.
- **Ingestion (Phase 1):** browsers upload straight to object storage as resumable S3 multipart uploads (`/api/v1/uploads`: create → presigned part URLs → complete). The `ingest.upload` job then:
  - computes the SHA-256 and links an exact duplicate to the existing video instead of storing it again;
  - stores the raw file once under a content-addressed key (`videos/<sha[:2]>/<sha>.<ext>`), never overwriting;
  - reads duration, resolution, FPS, codec, frame count, bit rate, and camera tags with ffprobe, and decodes the start of the stream — unreadable files become `corrupt` videos with the error, not crashes;
  - unpacks ZIPs into their videos, image-sequence folders (frame rate only if the uploader gave one), and JSON/CSV sidecars, which attach to the video with the same file name or to the session.

  `ingest.derivatives` then builds a 360p frame-exact proxy (one output frame per source frame) and a thumbnail strip in the derived bucket. Every upload, video, and sidecar is linked in `lineage_edges`.
- **Annotation (Phase 2):**
  - **Frame index:** after building the proxy, `ingest.derivatives` records every proxy frame's real timestamp, run-length encoded (`GET /api/v1/videos/{id}/frame-index`; one run for a constant-rate video of any length). The proxy has no B-frames, so each packet is one displayed frame in presentation order. `POST …/frame-index` builds it for videos ingested before it existed. Set `PROXY_CODEC=vp9` for browsers without H.264.
  - **Annotations** (`/api/v1/videos/{id}/annotations`, `/api/v1/annotations/{id}`): segments, boxes, and keypoints, with coordinates normalised to the frame. Every change appends a revision holding the full state after it (`…/history`). Deletes are soft and can be restored. Editing an AI annotation's content creates a new `auto_corrected` annotation and keeps the prediction, marked superseded. Stale edits are refused (`revision`).
  - **Timeline** (`GET /api/v1/videos/{id}/timeline`): per track, the annotations in the requested window, or counts per bucket when there are too many to draw.
  - **Queue** (`/api/v1/assignments`): reviewers and admins assign a session or a video to an annotator; progress counts videos with at least one human annotation.
- **Hand tracking (Phase 3):** `POST /api/v1/cv/runs` queues `cv.hand_tracking` on each video with the configured adapter. The chain is: frames (ffmpeg, numbered like the proxy) → adapter → persistent track IDs → One Euro smoothing → per-hand and per-finger kinematics.
  - **Swapping models:** set `HAND_TRACKING_ADAPTER` (a name in `egolabs/cv/registry.py` or `package.module:Class`) and `HAND_TRACKING_CONFIG` (JSON). No API or UI code changes. Adapters implement `load(config)`, `predict(frames)`, `metadata()` (`egolabs/cv/adapters/base.py`).
  - **Adapters:** `mediapipe-hands` (default; the model file is pinned by SHA-256 and baked into the image) and `keypoint-file` (another model's output as JSON Lines). RTMPose, YOLO-pose, TorchScript, and TensorFlow are documented stubs.
  - **Storage:** per-frame keypoints and finger features go to Parquet in the derived bucket, one file per 1,800 frames. Postgres holds summaries (`cv_runs`, `hand_tracks`) and one timeline segment per track. Every row carries its model version.
  - **Units:** speeds and accelerations are in source-video pixels per second. Visibility and occlusion are estimated from the keypoint geometry (MediaPipe reports no per-joint visibility).
- **Movement classification and object interaction (Phase 4):** `POST /api/v1/cv/runs` now queues, by default (`CV_DEFAULT_KINDS`), hand tracking and `cv.object_detection` on each video, plus a `cv.movement` run that waits (`waiting`) until both succeed and then starts on its own. So events land on the Phase 2 timeline from one request. `kinds: ["movement"]` re-classifies a video's latest hand and object runs.
  - **Object detection:** `OBJECT_DETECTION_ADAPTER` / `_CONFIG`. `mediapipe-objects` (default) is EfficientDet-Lite0 with COCO labels, pinned by SHA-256 and baked into the image; `person` is left out by default, since it is the camera wearer's own arm. `detections-file` imports another model's boxes; `yolo-objects` is a documented stub. Boxes are IoU-tracked and stored as Parquet, with an `object_tracks` summary row per object.
  - **Contact:** a fingertip inside an object's box (plus a margin of 0.12 hand sizes) counts as touching it. Contact segments go on the timeline's object-interaction track.
  - **Classifier:** `MOVEMENT_CLASSIFIER_ADAPTER` / `_CONFIG`, with the same `load` / `predict` / `metadata` pattern (`egolabs/cv/movement/base.py`). `rules` (default) implements all 20 spec classes as documented rules over pose, kinematics, and contact, each threshold configurable (`egolabs/cv/movement/rules.py`). `events-file` imports a learned model's events.
  - **Events** (`/api/v1/movement/events`): the spec's event record, plus a timeline segment (an AI annotation in the movement category). Each event stores its evidence: the exact hand-tracking frames it came from and the per-frame values the rule compared. Before an event is stored, the job checks that every evidence frame is a keypoint row of that track. `…/{id}/evidence` reads those rows back from Parquet. Events below `MOVEMENT_REVIEW_CONFIDENCE` (0.6) start as `needs_review`.
  - **Review:** `PATCH …/{id}` confirms, flags, or rejects an event; rejecting soft-deletes its segment. Correcting the segment in the inspector marks the event `corrected`.
  - **Classes** (`/api/v1/movement/classes`): the spec's built-ins, plus custom classes that admins and reviewers add, relabel, or switch off. Runs skip inactive classes.
  - **Graph** (`/api/v1/movement/graph`): Hand → Finger(s) → Movement → Object → Time range, for a video or session.
- **Review and active learning (Phase 5):** reviewing never gates processing. It records which labels a person has checked, so a dataset can choose them.
  - **Event versions:** a correction (`POST /api/v1/review/events/{id}/correct`, or editing the segment in the inspector) is a new event with `source: auto_corrected`, `parent_event_id` = the prediction, and its own timeline segment. The prediction is kept as the model made it, marked `corrected`. `GET …/{id}/history` lists the versions and the review log.
  - **Review log:** every status change is a `movement_event_reviews` row: from → to, who, and how (`individual`, `bulk`, `auto_rule`, `correction`, `inspector`, `undo`).
  - **Queue** (`GET /api/v1/review/queue`): pending events, most useful first. `priority` = `0.5·(1 − confidence) + 0.3·disagreement + 0.2·rarity` (`REVIEW_PRIORITY_WEIGHTS`), or sort by one term. Disagreement is 1 − the mean best temporal IoU with a same-class, same-hand event in each other model version's latest run on the video (unknown until a second version has run). Rarity puts a class between the most and least common on a log scale.
  - **Summary** (`/review/summary?group=class|object`): per-class or per-object counts for the review home's cards.
  - **Bulk review** (`/review/bulk/preview`, `/review/bulk`, `/review/batches/{id}/undo`): confirm or reject every pending event matching a filter, or a selection, as one batch (at most `REVIEW_BULK_MAX`). Undo puts back each event nobody has reviewed since. Admins and reviewers only.
  - **Auto-accept rules** (`/review/rules`): new predictions at or above a confidence are confirmed with no person (`auto_rule`): a default rule, and per-class rules that override it (a switched-off class rule opts the class out). Flagged events are never auto-accepted. `/review/rules/apply` applies them to pending events as an undoable batch.
  - **Metrics** (`/review/metrics`): correction and rejection rate, per-class accuracy (accepted ÷ human reviewed; auto-accepts never count), per-annotator throughput, reviews per day.
  - **Auto annotation** (`POST /review/auto-annotate`): the ready videos of chosen sessions, with a model per kind: the configured one, a registered version (`/review/model-versions`), or a new adapter + config (a new version).
- **Datasets, versioning and lineage (Phase 6):**
  - **Versions** (`POST /api/v1/datasets/{id}/versions`): a spec (filters and split) becomes the next version. Its inputs are pinned when it is created: the as-of time, the matching videos with their session and operator, and the latest classification run of each (so the model versions). A worker then writes every sample (annotation and event IDs, frames, class, review status, confidence, split) and a content hash: sha256 over the samples in a canonical order. A ready version and its samples can't change; database triggers refuse it.
  - **Filters:** session, device, environment, video, quality flags to leave out, class, review status (confirmed only by default; or human-verified only, leaving out auto-accepts), and confidence. `POST /datasets/preview` counts what a spec would take, per class and split, without saving anything.
  - **As of:** review status and corrections are read as they stood at the version's as-of time (from the review log and the annotation revisions), so later reviews never change what a version holds.
  - **Splits:** train/val/test by a seeded hash of the group, by session (default), operator, video, or sample, so one scene or one person never lands in two splits.
  - **Reproducibility** (`POST /datasets/versions/{id}/checks`): rebuilds the version from its recorded spec and inputs, and compares the hash.
  - **Exports** (`POST /datasets/versions/{id}/exports`, `/datasets/exports`): COCO (keypoints per split, a key frame per sample), JSON Lines, Parquet (samples, keypoints, objects), WebDataset (tar shards), and the native Ego Labs format (everything, plus evidence and raw-file provenance). Each is a zip in the derived bucket with a manifest and its sha256; `…/download` gives a 15-minute link straight from storage.
  - **Lineage** (`GET /datasets/samples/{id}/lineage`): the graph from a sample through its annotation, its movement event (and the prediction a correction replaced), model runs and versions, jobs, the video, upload and session, to the raw file (sha256) and its frames, and whether it reaches the raw file.
  - **Quality flags** on videos: `corrupt`, `variable_frame_rate`, and `hand_tracking_failures`, set at ingest and after hand tracking.
- **Pipelines (Phase 7):** a pipeline is a graph of steps; each step runs per video, or once for the whole run (dataset build, export).
  - **Steps** (`GET /api/v1/pipelines/steps`, `egolabs/pipelines/steps.py`): ingest check, extract frames, hand tracking, finger tracking, object detection, movement classification, the blur / low-light / occlusion / near-duplicate checks, annotated video, dataset build, and export. Each has a config model (its defaults are written into the saved version) and what it needs before it. Model steps call the Phase 3–4 job code inline, so they make the same model runs, with the step's job as their job.
  - **Versions** (`/pipelines`, `/pipelines/{id}`): saving a changed graph makes the next immutable version (a database trigger refuses changes); moving steps only changes the layout. `POST /pipelines/validate` checks a graph: known steps (each once), valid settings, no loops, requirements before each step, no per-video step after a whole-run one. Built-in templates (`/pipelines/templates`) and any pipeline saved with `is_template` are starting points.
  - **Runs** (`POST /pipelines/{id}/runs`, `/pipelines/runs`): the selected videos (sessions, datasets, or all; ingested ones only) are pinned; each node gets a step row per video. Each attempt is its own job with its own log. A failed step blocks only what depends on it; `POST /runs/{id}/retry` makes a new attempt of the failed steps and nothing else, and the steps waiting on them carry on. A step's `retries` retry it on its own after a transient failure (storage down, a worker lost), waiting longer each time (`PIPELINE_RETRY_BACKOFF_S`). `POST /runs/{id}/cancel` stops what hasn't started.
  - **Logs** (`/runs/{id}/logs`, `/runs/{id}/logs.txt`): the engine's own lines (what it queued, skipped, retried) plus every attempt's job log, in order; searchable by any fragment of a message or its data (a trigram index), filterable by level, step, and video.
  - **On new uploads:** a pipeline with `run_on_upload` starts a run (trigger `upload`, as the uploader) on each video right after ingest marks it ready (`egolabs/pipelines/auto.py`). Corrupt videos aren't processed, a pipeline never runs twice on a video this way, and a pipeline that can't start is logged on the ingest job without failing the upload.
  - **Scheduler:** the `scheduler` service (Celery beat) sends a tick every minute that fires due schedules, queues due retries, and fails jobs whose worker died (no heartbeat for `JOB_STALE_AFTER_S`; jobs beat every `JOB_HEARTBEAT_S`). Schedules (`/pipelines/schedules`) are cron expressions in a time zone (daylight saving handled; `POST /schedules/preview` shows the next times) and can take only the videos the pipeline hasn't processed yet.
  - **Quality checks** (`egolabs/quality_checks.py`, `GET /videos/{id}/quality`): blur (variance of the Laplacian of sampled frames at 640 px), low light (mean brightness), occlusion (share of the hand run's finger observations marked occluded), and near-duplicates (a 64-bit dHash per sampled frame; candidates through four indexed 16-bit bands, probed with each bit flipped, so pairs within 7 bits are found without a scan). Each stores its measurements and thresholds and sets or clears its flag (`blurry`, `low_light`, `high_occlusion`, `near_duplicate`), which the dataset builder can leave out.
  - **Annotated videos** (`egolabs/render.py`, `/videos/{id}/annotated`, `/annotated-videos/{id}/download`): every frame with the hand skeletons, object boxes, and current movement events drawn on, encoded as MP4 (H.264) or WebM (VP9), from a pipeline step or the video page.
- **`make seed`:** the only way to get sample data. It builds clips from MediaPipe's test photos: hands alone, and a hand cut out along its landmarks reaching for, grasping, carrying, pressing, and tapping an object photo. It uploads them into one session (task "Seed data (make seed)") through the API and runs the real hand → object → movement chain on them: `make seed SEED_EMAIL=you@gmail.com` (an account that has signed in once, as admin, annotator, or reviewer; it gets a token with `egolabs.token`).
- **Sessions:** named `SESSION_YYYY_MM_DD_NNN` (next number per day, allocated under a lock), with operator, device, start/end, environment, task, location, and capture conditions.
- **Storage URLs:** `S3_PUBLIC_ENDPOINT_URL` is the address browsers use to reach storage; upload and playback URLs are signed for it.
- **Logs:** JSON lines on stdout from the API and workers.
- **Tests:** `make test-backend` — runs against a real PostgreSQL (`TEST_DATABASE_URL`, default `egolabs_test` on localhost), building the schema with the migrations each run.

## Web app

```bash
cd web
cp .env.example .env.local   # API_URL, defaults to http://localhost:8000
npm install
npm run dev                  # http://localhost:3000
```

Checks: `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`.

- **Auth:** `/login` has one button, "Continue with Google". `/auth/google` sends the browser to Google with a random `state` and a PKCE challenge (kept in a 10-minute httpOnly cookie); `/auth/google/callback` checks the state, has the API finish signing in, and keeps the token in an httpOnly cookie. Signing in lands on `/dashboard` (or the page that asked for it). The landing page at `/` is public; `proxy.ts` sends signed-out visitors anywhere else to sign-in, and the app layout checks the session with the API on every request. `/register` now redirects to `/login`.
- **Dashboard** (`/dashboard`): the pipeline levels, from raw video to export, with a real count each (each level is live once its pages are built, from `web/lib/nav.ts`), the latest pipeline runs, the jobs in motion, and the activity stream. Light and dark themes follow the system until someone picks one with the toggle. The app shows the current plan (Phases 0–7): pages of later, optional phases stay listed in `web/lib/nav.ts` but hidden until `PLAN_LAST_PHASE` is raised.
- **API types:** generated from the FastAPI schemas — `web/lib/api/openapi.json` and `web/lib/api/schema.ts` are build outputs of `make gen-api`, never edited by hand. CI fails if they are stale.
- **Data pages (Phase 1):** Upload (drag-and-drop, pause/resume, resumes after a reload by re-adding the same file), Video Library (server-side filter/sort/paging), video detail (proxy player, thumbnail strip, ffprobe metadata, provenance, sidecars), Sessions, new session, session detail (videos, errors, dataset membership), and Devices. Client components reach the API through the same-origin gateway at `/api/v1/*`, which adds the session token server-side.
- **Video Inspector (Phase 2):** `/annotation/inspector/{videoId}` — proxy player with box/keypoint overlays and drawing, annotation panel (list, edit form, full history), and a seven-track timeline that zooms from the whole video down to single frames. The frame number shown is the frame the browser actually presents (`requestVideoFrameCallback`), mapped through the frame index. Shortcuts: Space, ←/→, Shift+←/→, A, R, Delete, Esc, `?`. The Annotation Queue (`/annotation/queue`) assigns sessions and videos to annotators.
- **Hand and Finger Tracking (Phase 3):**
  - `/cv/hands`: start runs, and see the active model and the runs table.
  - `/cv/hands/{run}`: skeleton overlay on the frame-exact player, detection and failure stats, the presence timeline, and tracks.
  - `/cv/fingers/{run}`: per-finger speed, acceleration, and visibility as small multiples on a shared scale, plus a table view.
  - The inspector draws the latest run's skeletons too.
- **Movement Classification and Object Tracking (Phase 4):**
  - `/cv/movements`: events, filterable by video, class, status, hand, finger, and confidence; the interaction graph for a video; the classifier; and re-classification.
  - `/cv/movements/events/{id}`: the event in the player with its hand's skeleton and its object's box, its evidence frames on a timeline, and a chart per measurement with the threshold it was held to. Below that are the keypoint rows themselves (click one to show that frame), plus confirm, flag, and reject.
  - `/cv/movements/classes`: the taxonomy.
  - `/cv/objects` and `/cv/objects/{run}`: box overlays, object tracks, and per-label stats.
  - The inspector draws object boxes; its object-interaction and movement tracks fill, and `?frame=N` opens it at a frame.
- **Review (Phase 5):**
  - `/annotation/review`: a card per movement class (or per object) with what is left, what is flagged, and how far review has got. Each card opens that class's own workspace.
  - `/annotation/review/work`: one event at a time from the queue. Its clip loops in the player with skeleton and object box, its evidence frames show as a strip, and it says why it is next. Keys: A accept, R reject, C correct, F flag, N/P next/previous, L loop; every verdict can be undone. Beside it is the queue, with select-and-accept and "Accept all…" (preview, then an undoable batch).
  - `/annotation/review/rules`: auto-accept rules, and the history of bulk reviews with undo.
  - `/annotation/review/metrics`: correction rate, accuracy per class, per-annotator throughput.
  - `/annotation/auto`: run auto annotation on sessions with a chosen model version.
  - Event pages show every version and the review log, and can correct the event.
- **Datasets (Phase 6):**
  - `/datasets/builder`: choose the dataset, filters, and split; a live preview counts samples per class and split (and warns when a split would be empty), then creates the version.
  - `/datasets/versions` and `/datasets/versions/{id}`: every version with its hash, parent, and split bar. A version page shows its recorded spec, pinned inputs, samples per class and split, and every sample, plus "Rebuild from spec" (the hash comparison) and exports in all five formats.
  - `/datasets/exports`: every export, with size, sha256, and download.
  - `/datasets/lineage/{sample}`: the lineage graph. It opens on the raw file and draws the path the sample came from; click any record to see what it holds.
- **Pipelines (Phase 7):**
  - `/pipelines/builder`: the graph editor: add steps from the palette, drag them, drag from a step's ● onto the next (or tick "Runs after"), set each step's settings and automatic retries, and save (a changed graph is the next version); tick "Save as a template" to list it on the Templates page, or "Run automatically on new uploads" to process every new video with it. "Run…" picks sessions, datasets, or all videos.
  - `/pipelines/runs` and `/pipelines/runs/{id}`: each run's progress; on a run, the graph with each step's status, every step per video with its attempts, duration, and failure reason, retry (one step, or all failed ones), cancel, the outputs (annotated videos to download, the dataset version), and the logs: search, level filter, one step's lines, live while it runs, and download.
  - `/pipelines/schedules`: cron schedules with presets, a time zone, the next times, and run now. `/pipelines/templates`: the built-in templates and saved ones, each with its graph.
  - Video pages show the annotated videos (render, watch, download) and the quality checks.
- **No placeholder numbers:** the dashboard reads `GET /api/v1/overview` and the lists behind each count; when there's no data it shows empty states. Pages from later phases render "Not yet built" with the phase that delivers them (see `web/lib/nav.ts`).
- **Components** in `web/components/ui/`: `DataTable` (controlled sort/filter/paging for server-side queries, plus `useLocalTable` for small lists), `StatCard`, `StatusBadge`, `ConfidenceBadge`, `SourceBadge` (AI vs human), `EmptyState`, and `Timeline` (multi-track, renders only the segments in view).

## CI

`.github/workflows/ci.yml` runs backend lint + tests (with Postgres and Redis services), web lint + typecheck + tests + build, checks the generated API types are current, then builds and starts the whole stack with `docker compose up --wait` and runs `scripts/smoke.sh` against it (including a direct-to-storage upload, a duplicate, and a corrupt file).
