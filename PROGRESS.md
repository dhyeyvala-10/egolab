# PROGRESS

Build progress against the [Ego Labs phased build spec](docs/ego-labs-phased-spec.md).
This file is the progress record: update it at the end of each phase. The current plan is Phases 0–7; Phases 8–11 are optional and not scheduled.

- **Last updated:** 2026-09-25
- **Current phase:** the plan is done (Phases 0–7); Phases 8–11 are optional
- **Phases complete:** 8 of the 8 planned (0–7)

| Phase | Status | Build | Acceptance |
| --- | --- | --- | --- |
| 0 — Foundation | Complete | 5/5 | 3/3 |
| 1 — Ingestion & Sessions | Complete | 6/6 | 3/3 |
| 2 — Video Inspector & Manual Annotation | Complete | 7/7 | 3/3 |
| 3 — CV Worker & Hand/Finger Tracking | Complete | 8/8 | 3/3 |
| 4 — Movement Classification & Object Interaction | Complete | 6/6 | 2/2 |
| 5 — Review & Active Learning | Complete | 4/4 | 2/2 |
| 6 — Datasets, Versioning & Lineage | Complete | 5/5 | 2/2 |
| 7 — Pipelines | Complete | 4/4 | 2/2 |
| 8 — Models & Evaluation | Not in the current plan | 0/4 | — |
| 9 — Real-Time & Overview Command Center | Not in the current plan | 0/5 | 0/1 |
| 10 — Mobile App (React Native / Expo) | Not in the current plan | 0/4 | — |
| 11 — Differentiators | Not in the current plan | 0/5 | — |

## Phase 0 — Foundation

Status: **Complete**

Goal: A running skeleton with the data model and design system in place.

### Build

- [x] Docker Compose: Postgres, Redis, MinIO, API, worker, web.
- [x] Auth: email/password with roles (`admin`, `annotator`, `reviewer`, `viewer`).
- [x] Core schema:
  - `datasets`, `sessions`, `videos`, `frames` (frames are virtual rows or indexed lazily, not one row per frame at ingest)
  - `devices`, `operators`
  - `jobs`, `job_logs`
  - `model_versions`
  - `annotations` (with `source`, `confidence`, `model_version_id`, `parent_annotation_id`, `created_by`)
  - `events` (activity stream)
  - `lineage_edges` (generic parent → child links between any two entities)
- [x] App shell: sidebar with all navigation sections (Overview, Data, Annotation, Computer Vision, Pipelines, Datasets, Models, Real-Time, Experiments, Infrastructure, Settings). Unbuilt pages show a clean "Not yet built" state.
- [x] Reusable components: DataTable, StatCard, StatusBadge, ConfidenceBadge, EmptyState, Timeline primitive.

### Acceptance criteria

- [x] `docker compose up` starts everything with no errors.
- [x] A user can register, log in, and see the app shell.
- [x] Migrations run cleanly from an empty database.

### Notes

Web: web/ (Next.js 16, Tailwind 4, Vitest) — app shell with all 11 sections, "Not yet built" pages, sign-in/registration with an httpOnly session cookie, Overview from GET /api/v1/overview. API types are generated from the FastAPI schemas (make gen-api).
Backend: backend/ (FastAPI, SQLAlchemy 2, Alembic, Celery) — full core schema with CHECK constraints for the product principles, email/password auth with admin/annotator/reviewer/viewer roles (first account is admin), structured job logs, system.healthcheck job. 46 tests against real PostgreSQL.
Verified locally: migrations from an empty database, register → sign in → app shell in a browser, worker completing a job (scripts/smoke.sh).
Compose: verified in CI (PR #2) — `docker compose up --build --wait` brings every service up healthy and scripts/smoke.sh passes (register, login, overview, worker job against MinIO, web redirect). MinIO is built from source release RELEASE.2025-10-15T17-29-55Z because MinIO no longer publishes images.

## Phase 1 — Ingestion & Sessions

Status: **Complete**

Goal: Upload real videos, organise them, and never store duplicates.

### Build

- [x] Upload page: drag-and-drop, resumable multipart uploads direct to object storage.
- [x] Supported inputs: MP4, MOV, AVI, MKV, image sequences, ZIP archives, JSON/CSV metadata sidecars.
- [x] On upload, a worker:
  - computes SHA-256 checksum; rejects exact duplicates and links to the existing record
  - runs ffprobe: duration, resolution, FPS, codec, file size
  - extracts camera metadata if present
  - flags corrupt/unreadable files
  - generates a thumbnail strip and a low-res proxy for fast playback
- [x] Hierarchy: Dataset → Session → Video → Frame.
- [x] Session naming: `SESSION_YYYY_MM_DD_NNN`, with operator, device, start/end time, environment, task, location, capture conditions.
- [x] Pages: Video Library (filterable table), Sessions list, Session detail (videos, status, errors, dataset membership), Devices.

### Acceptance criteria

- [x] Uploading the same file twice creates one video record.
- [x] A corrupt file is flagged, not crashed on.
- [x] All metadata shown in the UI comes from ffprobe or user input.

### Notes

Uploads go browser → storage as resumable S3 multipart uploads (presigned parts; pause, and resume after a reload by re-adding the file). ingest.upload: SHA-256 → exact duplicates linked to the existing video → content-addressed raw object → ffprobe + decode check (corrupt files flagged with the error) → ZIPs unpacked into videos, image-sequence folders, and JSON/CSV sidecars. ingest.derivatives: 360p frame-exact proxy + thumbnail strip.
Pages: Upload, Video Library, video detail, Sessions, new session, session detail (videos, errors, datasets), Devices.
Acceptance: duplicate → one video record, corrupt → flagged, metadata = ffprobe output — covered by backend tests (moto S3 + real ffmpeg), a browser run against real MinIO, and the CI compose smoke test.
Note: MinIO is built from source (no published images); Playwright's Chromium can't decode H.264, so proxy playback was checked by serving, and frame-exactness by ffprobe.

## Phase 2 — Video Inspector & Manual Annotation

Status: **Complete**

Goal: Frame-accurate inspection and human annotation.

### Build

- [x] Layout: video player (left), annotation panel (right), multi-track timeline (bottom).
- [x] Frame-accurate seeking (use the proxy video plus frame index).
- [x] Timeline tracks: hand detections, finger activity, object interactions, movement events, human annotations, AI annotations, pipeline events. Tracks are empty until later phases fill them.
- [x] Keyboard shortcuts:
  - Space: play/pause
  - ← / →: previous / next frame
  - Shift + ← / →: previous / next event
  - A: create annotation
  - R: mark for review
  - Delete: remove annotation (soft delete, kept in history)
- [x] Annotation types: temporal segment, bounding box, keypoint.
- [x] Annotation Queue page: assign sessions/videos to annotators.
- [x] Full edit history per annotation.

### Acceptance criteria

- [x] Stepping frames is exact (frame N shows frame N).
- [x] Deleting an annotation keeps it in history.
- [x] Timeline stays smooth on a 30-minute video.

### Notes

Inspector at /annotation/inspector/{video}: proxy player with box/keypoint overlays and drawing, annotation panel (list, edit, full history), seven-track timeline (hand, finger, object, movement, human, AI, pipeline; CV tracks empty until Phases 3–4). Frame index: every proxy frame's real timestamp, run-length encoded; the proxy has no B-frames; the frame number shown is the frame the browser presents (requestVideoFrameCallback). Annotations: segment/box/keypoint, every change is a revision with the full state; deletes are soft and restorable; editing an AI annotation creates an auto_corrected copy and keeps the prediction. Timeline API returns density buckets when a track is too busy. Queue: reviewers/admins assign sessions or videos; progress = videos with a human annotation. Migration 0003.
Acceptance, verified in a real browser against the live stack: frame N shows frame N — 192 frame checks on constant- and variable-rate clips whose frames show their own number (picture decoded from screenshots); delete keeps history (created → updated → flagged → deleted, then restored); 30-minute video (54,000 frames, 27,000 detections + 2,100 segments) stays at 60 fps while zooming, panning, and playing (p99 16.8 ms, no long tasks). 107 backend and 56 web tests; smoke test covers frame index, soft delete, and timeline.

## Phase 3 — CV Worker & Hand/Finger Tracking

Status: **Complete**

Goal: Real hand and finger tracking through a swappable adapter.

### Build

- [x] Model adapter interface (Python):
  - `load(config)`, `predict(frames) -> HandResult[]`, `metadata() -> {name, version, keypoint_schema}`
- [x] First adapter: MediaPipe Hands. Stub interfaces documented for RTMPose, YOLO-pose, custom PyTorch/TensorFlow.
- [x] Processing chain: frame extraction → hand detection → 21-keypoint estimation → tracking (persistent track IDs) → temporal smoothing (e.g. One Euro filter).
- [x] Per hand per frame: frame ID, timestamp, left/right, bounding box, wrist position, keypoints, confidence, track ID.
- [x] Per finger (thumb, index, middle, ring, pinky): fingertip and joint coordinates, orientation, velocity, acceleration, visibility, occlusion flag, confidence.
- [x] Derived kinematics: displacement, velocity, direction, acceleration, trajectory.
- [x] Storage: keypoints in columnar files (Parquet) in object storage, with summary rows in Postgres. Do not store millions of keypoint rows in Postgres.
- [x] Hand Tracking and Finger Tracking pages: overlay skeletons on video, per-finger velocity charts, missing-detection and tracking-failure stats.

### Acceptance criteria

- [x] Running tracking on a sample video produces visible, correct overlays.
- [x] Swapping the adapter via config works without touching UI or API code.
- [x] Every output row references a model version.

### Notes

Adapter interface (load/predict/metadata/reset) in egolabs/cv/adapters/base.py; chosen by HAND_TRACKING_ADAPTER + HAND_TRACKING_CONFIG. mediapipe-hands (MediaPipe 1.0.1, hand_landmarker.task pinned by SHA-256, baked into the image) and keypoint-file (other models' output as JSON Lines); RTMPose, YOLO-pose, TorchScript, and TensorFlow documented as stubs. Chain: ffmpeg frames → adapter → greedy IoU/wrist tracker with persistent IDs (missing detections, tracking failures) → One Euro smoothing in pixels → wrist and fingertip velocity/acceleration/direction/path, finger orientation, visibility, estimated occlusion. Parquet per 1,800 frames in the derived bucket; cv_runs + hand_tracks summaries; one timeline segment per track and finger-activity segments; lineage video/model_version → run. Pages: Hand Tracking (runs, overlay player, presence timeline, tracks), Finger Tracking (small-multiple charts, per-finger stats); skeletons in the inspector. make seed runs real tracking on sample clips. Migration 0004.
Acceptance: overlays are correct — clips of MediaPipe's own test photos moved with a known transform per frame; raw keypoints within 3 px mean of the published landmarks (tests), and in the browser the overlay draws exactly the stored keypoints (0 px) at 0.8–2.6% of hand size from ground truth. Adapter swapped by config alone on the live stack (mediapipe-hands → keypoint-file → back) from the unchanged UI. Every Parquet row, track, annotation, and run references its model version (asserted in tests). 122 backend and 59 web tests.

## Phase 4 — Movement Classification & Object Interaction

Status: **Complete**

Goal: Turn keypoints into meaningful, confidence-scored events.

### Build

- [x] Movement classes (editable, custom classes allowed): hand enters/exits frame, reach, grasp, release, pinch, point, tap, swipe, rotate, push, pull, pick up, put down, hold, move, manipulate, press, drag, gesture.
- [x] Classifier adapter interface, same pattern as Phase 3. Start with a rule-based classifier using finger kinematics (e.g. pinch = thumb–index distance below threshold for N frames); allow a learned model later.
- [x] Object detection adapter (e.g. YOLO) and hand–object contact detection.
- [x] Event record: Event ID, Session ID, Video ID, start/end frame, start/end timestamp, class, hand, finger(s), object, confidence, model version, status (`auto_detected`, `needs_review`, `confirmed`, `rejected`, `corrected`).
- [x] Interaction graph: Hand → Finger(s) → Movement → Object → Time range.
- [x] Movement Classification and Object Tracking pages.

### Acceptance criteria

- [x] Events appear on the Phase 2 timeline automatically.
- [x] Each event links back to the exact keypoint frames that produced it.

### Notes

Object detection: OBJECT_DETECTION_ADAPTER (mediapipe-objects = EfficientDet-Lite0/COCO, pinned and baked; detections-file; yolo-objects stub), IoU tracking, Parquet boxes + object_tracks. Hand–object contact: fingertips inside an object's box (+0.12 hand sizes). Classifier: MOVEMENT_CLASSIFIER_ADAPTER, same load/predict/metadata pattern; `rules` implements all 20 spec classes as documented, configurable rules over pose, kinematics, and contact; `events-file` imports a learned model's events. Runs chain: POST /cv/runs queues hand tracking + object detection and a movement run that waits for both. Events: movement_events (spec record) + a movement-category AI annotation; evidence = exact hand-tracking frames + per-frame measurements, checked against the Parquet rows before storing. Editable classes (built-ins + custom, on/off), review (confirm/flag/reject; inspector corrections mark events corrected), interaction graph. Migration 0005.
Acceptance: events on the Phase 2 timeline automatically — a run started from the Hand Tracking page put all 9 events of the grasp clip (enter, reach, grasp, hold, pick up, move left, put down, release, exit — the scripted motion, in order) and the hand–burger contact on the inspector's timeline with no further step (browser, live stack with Celery). Each event links back to its exact keypoint frames — the event page lists the evidence rows read back from the hand run's Parquet (matching the event record frame for frame), the overlay draws them 0 px off, measurements recompute from them; tests check every event of the sample clips the same way. 157 backend and 65 web tests; make seed and the smoke test run the full chain.

## Phase 5 — Review & Active Learning

Status: **Complete**

Goal: Efficient human correction, prioritising where the model is weakest.

### Build

- [x] Review page: accept / reject / correct auto annotations; corrections keep the original as a parent.
- [x] Active-learning queue: sort review items by lowest confidence, highest model disagreement, and rarest class first.
- [x] Metrics: human correction rate, per-class accuracy against human review, per-annotator throughput.
- [x] Auto Annotation page: run auto-annotation on selected sessions with a chosen model version.

### Acceptance criteria

- [x] Correcting an event creates a new version and keeps the old one.
- [x] The queue order visibly changes when confidence data changes.

### Notes

Review home at /annotation/review: one card per movement class (or per object) with what is left, flagged, and reviewed; each opens its own workspace. Workspace: the event's clip loops in the player with skeleton and object box, evidence frames as a strip, why it is in the queue (priority parts); keys A accept, R reject, C correct, F flag, N/P next/previous; undo on every verdict. Active-learning queue: priority = 0.5·(1 − confidence) + 0.3·disagreement + 0.2·class rarity (REVIEW_PRIORITY_WEIGHTS), or sort by any one of them; disagreement = 1 − mean best temporal IoU with other model versions' latest runs on the video. Corrections are new event versions (source auto_corrected, parent = the prediction, own timeline segment); the prediction is kept, marked corrected; inspector edits do the same. Every status change is in a review log (who, how: individual, bulk, auto_rule, correction, inspector, undo). Added at the user's request: auto-accept rules (default + per class, never for flagged events, recorded as auto_rule and excluded from accuracy), bulk accept/reject of a filtered view or a selection with preview and undo, grouping by class or object. Metrics: correction and rejection rate, per-class accuracy against human review, per-annotator throughput and reviews per day. Auto Annotation: sessions × chosen model version per kind (registered version or a new config = new version). Migration 0006.
Acceptance, verified in a real browser against the live stack: a correction from the workspace created v2 (Gesture, AI · corrected, parent = the prediction, its own segment on the timeline) while v1 (Point, 0.98) stayed as predicted, marked corrected; re-running the seed session from the Auto Annotation page with a new classifier config (a new model version) reordered the confidence queue (the grasp clip's reach fell 0.55 → 0.48, a hold and a short reach dropped out) and every item was compared with the first version. Bulk accept of a class with preview → undo, rules applied to 14 pending predictions → undo, no horizontal overflow at 390 px. 178 backend and 71 web tests.

## Phase 6 — Datasets, Versioning & Lineage

Status: **Complete**

Goal: Reproducible, exportable training datasets.

### Build

- [x] Dataset builder: filter by session, class, confidence, review status, quality flags, device, environment.
- [x] Every dataset version stores: exact filters, included annotation IDs, model versions, and a content hash. Versions are immutable.
- [x] Splits: train/val/test with options to split by session or operator (to avoid leakage).
- [x] Exports: COCO, JSON Lines, Parquet, WebDataset, and a native Ego Labs format.
- [x] Lineage graph view: click any exported sample to trace it back through annotations, model versions, processing jobs, and the raw frame.

### Acceptance criteria

- [x] Rebuilding a dataset version from its recorded spec gives an identical hash.
- [x] Lineage view reaches the raw file from any sample.

### Notes

Dataset Builder at /datasets/builder: filter by session, device, environment, video, quality flags (corrupt, variable frame rate, hand-tracking failures; set at ingest and after hand tracking), class, review status (and human-verified only), and confidence, with a live preview of samples per class and split. A version is immutable: it records the exact spec (filters and split), its pinned inputs (as-of time; the videos with their session and operator; the classification runs and model versions used), every included sample (annotation and event IDs, frames, class, review status, confidence, split) and a content hash (sha256 over the samples in canonical order); database triggers refuse any change to a ready version or its samples. Review status and corrections resolve as they stood at the as-of time, so later reviews never change a version. Splits: train/val/test by a seeded hash of the group, by session (default), operator, video, or sample, so a scene or a person never lands in two splits. Exports: COCO, JSON Lines, Parquet, WebDataset, and the native Ego Labs format (everything plus evidence and raw-file provenance), each a zip with a manifest and sha256, downloaded through a short-lived link. Lineage at /datasets/lineage/{sample}: a graph from the sample through its annotation, movement event (and the prediction a correction replaced), model runs and versions, jobs, video, upload and session to the raw file (sha256) and its frames. Migration 0007. The dashboard redesign (PR #7) is merged in: Dataset Versioning and Export are live on the dashboard, with counts of ready versions and exports.
Acceptance, verified in a real browser against the live stack: v1 of "Seed movements" (32 samples from the 5 seed videos, 60/20/20 by video) hashed f0c5f2eb…; after confirming, rejecting and correcting events and re-classifying a video with a new rules config, "Rebuild from spec" gave the identical hash (32 samples), while v2 built from the same spec on the changed data hashed 0ffd5b5b…, with v1 as its parent. All five exports built and downloaded. Every sample of both versions (64) traced on its lineage page to the raw file with the matching sha256; corrected samples pass through the prediction they replaced. No horizontal overflow at 390 px on any Phase 6 page. 187 backend and 90 web tests.

## Phase 7 — Pipelines

Status: **Complete**

Goal: Composable, logged, schedulable processing.

### Build

- [x] Pipeline Builder: visual DAG of steps (ingest, extract frames, hand tracking, finger tracking, object detection, movement classification, quality checks, dataset build, export).
- [x] Runs page: status per step, duration, logs, retries, failure reasons.
- [x] Schedules (cron-style) and Templates.
- [x] Quality-check steps: blur detection, low-light detection, occlusion rate, duplicate/near-duplicate detection.

### Acceptance criteria

- [x] A failed step can be retried without rerunning completed steps.
- [x] Every run has complete, searchable logs.

### Notes

Pipeline Builder at /pipelines/builder: steps from a palette (ingest check, extract frames, hand tracking, finger tracking, object detection, movement classification, blur, low-light, occlusion and near-duplicate checks, annotated video, dataset build, export) on a canvas: drag to arrange, drag from a step's handle onto the next (or tick "Runs after") to connect, each step's settings from its schema, live validation (no loops, requirements such as finger tracking after hand tracking, no per-video step after a whole-run one). Saving a changed graph makes the next immutable version (a trigger refuses changes); moving steps only saves the layout. Runs pin their videos and make a step row per node and video (dataset build and export once per run); each attempt is its own job with its own structured log; model steps reuse the Phase 3–4 code, so they make the same model runs. A failed step stops only what depends on it; retrying makes a new attempt of that step alone, and the steps waiting on it carry on. Steps can also retry on their own after transient failures (storage down, a worker lost: jobs send heartbeats and the scheduler recovers orphans). Runs page: progress, duration, and trigger per run; run page: the graph with each step's status, every step per video with attempts, durations and failure reasons, retry and cancel, outputs, and the run's logs (the engine's lines plus every attempt's job log), searchable by any fragment of a message or its data (trigram index), filterable by level and step, and downloadable. Schedules: cron with presets and time zones (daylight saving handled), "only videos this pipeline hasn't processed", a preview of the next times, and "Run now"; a scheduler service (Celery beat) sends the tick every minute. Templates: five built-in starting points, and any pipeline can be saved as one. Quality checks store their measurements and thresholds and set flags the dataset builder can leave out (blurry, low_light, high_occlusion, near_duplicate); near-duplicates are found through indexed 16-bit bands of frame dHashes. Added at the user's request: annotated videos (hand skeletons, object boxes, and movement events drawn on every frame), as a pipeline step and from the video page, to download (MP4 or WebM) or watch in the page. The dashboard shows the current plan only (Phases 8–11 hidden), with the latest pipeline runs; the white build tracker was removed. Migration 0008.
Acceptance, verified in a real browser against the live stack: "Process videos" (from its template) ran on the 5 seed videos with one video's raw file taken out of storage; 44 steps succeeded, that video's ingest check failed ("missing from storage") and its 10 later steps waited. With the file put back (byte-identical), "Retry 1 failed step" made attempt 2 of that step only; the 10 waiting steps then ran once each, the run finished 55/55, and all 44 completed steps kept their attempt count, job, result and finish time (56 attempts for 55 steps). The run's log had 426 lines on the page, in the database (57 jobs, every one with lines) and in the downloaded .log alike; searching "missing from storage" found the 3 failure lines, the step filter showed both attempts, the level filter the 4 error lines. The annotated grasp video downloaded (H.264, 640×480, all 260 frames, skeleton and labels drawn) and a WebM render played in the page. A schedule (every night at 02:00, Asia/Kolkata) previewed 26 Sept 02:00 IST (20:30 UTC) and "Run now" found no new videos. A pipeline saved as a template appeared on the Templates page, and "Use template" copied its graph into a new pipeline. No horizontal overflow at 390 px on any Phase 7 page. 200 backend and 98 web tests; the smoke test runs a pipeline too.

## After the plan

- [x] Sign-in with Google (asked for after Phase 7): one login page with "Continue with Google"; the first sign-in creates the account (first admin, then viewers); signing in lands on the dashboard. Password sign-in only for scripts (`PASSWORD_LOGIN`). Migration 0009.
- [x] Processing by itself (asked for after the Google sign-in): a pipeline can run automatically on every new upload once its checks finish ("Run automatically on new uploads" in the builder; runs show as "New upload"). Every container restarts on its own. Migration 0010.
- [x] The owner in control (asked for once online): `OWNER_EMAIL` is the only admin, whom nobody can change; newcomers get no access until given a role; Settings → Users, Requests, Limits, Activity; uploads over the size limit wait before anything is sent, videos over the length limit wait before anything processes them; only the owner starts processing unless they allow editors; people see only their own uploads and activity; the Upload page shows who sent what, how much has arrived, and whether it has stopped, with Cancel. Migration 0011.

### Notes

The API exchanges Google's code with the client secret and verifies the ID token against Google's published keys (audience, issuer, expiry, verified email); accounts are found by Google's id, linked by email, or created. The web app sends a random state and a PKCE challenge, kept in a short-lived httpOnly cookie. Verified in Chromium against a local stand-in for Google's endpoints (backend/tests/fake_google.py, which checks the client secret, redirect URI and PKCE verifier as Google does): the existing admin was linked by email and landed on the dashboard, a new Google account became a viewer, a cancelled sign-in and a forged callback were refused. The browser check caught the callback being built from the server's own host name rather than the browser's (the cookie then didn't come back); addresses now come from the Host header or PUBLIC_WEB_URL. Setup steps for Google Cloud are in the README.

## Phase 8 — Models & Evaluation

Status: **Not in the current plan** (optional)

### Build

- [ ] Model Registry: every adapter version with config, metrics, and which datasets it was evaluated on.
- [ ] Inference page: run any registered model on selected videos.
- [ ] Evaluation: compare model versions against human-reviewed ground truth (precision, recall, F1 per class, keypoint error).
- [ ] Experiments page: record configurations and results side by side.

### Notes

_None yet._

## Phase 9 — Real-Time & Overview Command Center

Status: **Not in the current plan** (optional)

### Build

- [ ] Event Stream: live WebSocket feed of system events ("Session uploaded", "Hand tracking completed", "Movement detected: PICK_UP", "Human review required", "Dataset v14 created").
- [ ] Live Processing: active jobs, queue depth, processing FPS, inference latency.
- [ ] Infrastructure: worker health, GPU/CPU utilisation (from real worker telemetry).
- [ ] System Logs: searchable, filterable.
- [ ] Overview page with dataset stats, processing metrics, data quality metrics, and the live activity stream, all computed from real data.

### Acceptance criteria

- [ ] Every Overview number can be clicked through to the records behind it.

### Notes

_None yet._

## Phase 10 — Mobile App (React Native / Expo)

Status: **Not in the current plan** (optional)

### Scope (do not clone the web app)

- [ ] Capture and upload video from the phone with session metadata.
- [ ] Review queue: accept/reject/correct events on short clips.
- [ ] Monitoring: job status and push notifications for failures and review requests.
- [ ] Read-only session and dataset browsing.

### Notes

_None yet._

## Phase 11 — Differentiators

Status: **Not in the current plan** (optional)

### Build

- [ ] **Human-to-robot retargeting export.** Map finger trajectories to robot hand and gripper kinematics (parallel gripper, multi-finger hands) with configurable embodiment profiles. Export ready-to-train action sequences.
- [ ] **Manipulation query language.** Search like: `hand:right movement:pinch object:screw lighting:low confidence<0.8`, returning matching clips instantly.
- [ ] **Skill discovery.** Cluster recurring movement patterns across sessions to suggest new movement classes nobody has defined yet.
- [ ] **Data coverage map.** Show which combinations of movement × object × environment are over- or under-represented, to guide what to record next.
- [ ] **Model disagreement view.** Run two model versions on the same video and highlight frames where they disagree.

### Notes

_None yet._
