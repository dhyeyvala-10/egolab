# Ego Labs — Phased Build Specification

An operating system for ingesting, processing, annotating, versioning, and exporting egocentric video data for robotics and ML training.

**Pipeline:** Raw Video → Ingestion → Processing → Hand/Finger Tracking → Movement Detection → Human Annotation → Dataset Versioning → Export → Evaluation & Monitoring

---

## How to use this spec

1. **Section A (Global Rules)** applies to every phase.
2. Build **one phase at a time**.
3. Do not start the next phase until every acceptance criterion in the current phase passes.
4. Keep `PROGRESS.md` in the repo up to date: update it at the end of each phase and read it before starting the next.

---

## A. GLOBAL RULES (apply to every phase)

**Product principles**
1. Every piece of data is traceable back to a raw file and frame.
2. Raw data is immutable. Never overwrite or delete source files.
3. Every processing operation creates a new version with a parent reference.
4. AI-generated annotations are always distinguishable from human annotations (`source: auto | human | auto_corrected`).
5. Humans can correct any AI annotation; the original prediction is preserved.
6. Every dataset version is reproducible from its recorded inputs, filters, and model versions.
7. Every job writes structured logs.
8. Every prediction carries a confidence score and a model version.
9. Design for very large volumes (millions of frames): paginate, stream, never load full tables into memory.
10. CV/ML models plug in through an adapter interface and can be swapped without code changes elsewhere.

**No fake data.** Every number, chart, status, and log must come from the database or live workers. If there is no data, show an empty state. Seed data is allowed only through a clearly labelled `make seed` script that runs real processing on sample videos.

**Tech stack**
- Web: Next.js (App Router) + TypeScript + Tailwind CSS
- API: FastAPI (Python 3.11+)
- Database: PostgreSQL (with JSONB for keypoints metadata)
- Queue/cache: Redis
- Workers: Celery (GPU-capable Python workers)
- Object storage: S3-compatible (MinIO locally)
- Video: ffmpeg / ffprobe
- Real-time: WebSockets or Server-Sent Events
- Mobile: React Native (Expo) sharing API types with web
- Local dev: Docker Compose for everything

**Design system**
- Light theme: black text on white, grey borders (#E5E5E5), neutral greys for secondary text. Optional dark mode later.
- Font: Plus Jakarta Sans.
- Dense, modular layout: compact cards, excellent sortable/filterable tables, subtle 1px borders, no gradients or decorative illustrations.
- Colour used only for meaning: status (success/warning/error), confidence, and AI vs human annotations.
- Left collapsible sidebar navigation.

**Code standards**
- Typed API schemas (Pydantic) with generated TypeScript client.
- Database migrations (Alembic).
- Tests for every API endpoint and worker task.
- No hardcoded secrets; use `.env`.

---

## PHASE 0 — Foundation

**Goal:** A running skeleton with the data model and design system in place.

**Build**
- Docker Compose: Postgres, Redis, MinIO, API, worker, web.
- Auth: email/password with roles (`admin`, `annotator`, `reviewer`, `viewer`).
- Core schema:
  - `datasets`, `sessions`, `videos`, `frames` (frames are virtual rows or indexed lazily, not one row per frame at ingest)
  - `devices`, `operators`
  - `jobs`, `job_logs`
  - `model_versions`
  - `annotations` (with `source`, `confidence`, `model_version_id`, `parent_annotation_id`, `created_by`)
  - `events` (activity stream)
  - `lineage_edges` (generic parent → child links between any two entities)
- App shell: sidebar with all navigation sections (Overview, Data, Annotation, Computer Vision, Pipelines, Datasets, Models, Real-Time, Experiments, Infrastructure, Settings). Unbuilt pages show a clean "Not yet built" state.
- Reusable components: DataTable, StatCard, StatusBadge, ConfidenceBadge, EmptyState, Timeline primitive.

**Acceptance criteria**
- `docker compose up` starts everything with no errors.
- A user can register, log in, and see the app shell.
- Migrations run cleanly from an empty database.

---

## PHASE 1 — Ingestion & Sessions

**Goal:** Upload real videos, organise them, and never store duplicates.

**Build**
- Upload page: drag-and-drop, resumable multipart uploads direct to object storage.
- Supported inputs: MP4, MOV, AVI, MKV, image sequences, ZIP archives, JSON/CSV metadata sidecars.
- On upload, a worker:
  - computes SHA-256 checksum; rejects exact duplicates and links to the existing record
  - runs ffprobe: duration, resolution, FPS, codec, file size
  - extracts camera metadata if present
  - flags corrupt/unreadable files
  - generates a thumbnail strip and a low-res proxy for fast playback
- Hierarchy: Dataset → Session → Video → Frame.
- Session naming: `SESSION_YYYY_MM_DD_NNN`, with operator, device, start/end time, environment, task, location, capture conditions.
- Pages: Video Library (filterable table), Sessions list, Session detail (videos, status, errors, dataset membership), Devices.

**Acceptance criteria**
- Uploading the same file twice creates one video record.
- A corrupt file is flagged, not crashed on.
- All metadata shown in the UI comes from ffprobe or user input.

---

## PHASE 2 — Video Inspector & Manual Annotation

**Goal:** Frame-accurate inspection and human annotation.

**Build**
- Layout: video player (left), annotation panel (right), multi-track timeline (bottom).
- Frame-accurate seeking (use the proxy video plus frame index).
- Timeline tracks: hand detections, finger activity, object interactions, movement events, human annotations, AI annotations, pipeline events. Tracks are empty until later phases fill them.
- Keyboard shortcuts:
  - Space: play/pause
  - ← / →: previous / next frame
  - Shift + ← / →: previous / next event
  - A: create annotation
  - R: mark for review
  - Delete: remove annotation (soft delete, kept in history)
- Annotation types: temporal segment, bounding box, keypoint.
- Annotation Queue page: assign sessions/videos to annotators.
- Full edit history per annotation.

**Acceptance criteria**
- Stepping frames is exact (frame N shows frame N).
- Deleting an annotation keeps it in history.
- Timeline stays smooth on a 30-minute video.

---

## PHASE 3 — CV Worker & Hand/Finger Tracking

**Goal:** Real hand and finger tracking through a swappable adapter.

**Build**
- Model adapter interface (Python):
  - `load(config)`, `predict(frames) -> HandResult[]`, `metadata() -> {name, version, keypoint_schema}`
- First adapter: MediaPipe Hands. Stub interfaces documented for RTMPose, YOLO-pose, custom PyTorch/TensorFlow.
- Processing chain: frame extraction → hand detection → 21-keypoint estimation → tracking (persistent track IDs) → temporal smoothing (e.g. One Euro filter).
- Per hand per frame: frame ID, timestamp, left/right, bounding box, wrist position, keypoints, confidence, track ID.
- Per finger (thumb, index, middle, ring, pinky): fingertip and joint coordinates, orientation, velocity, acceleration, visibility, occlusion flag, confidence.
- Derived kinematics: displacement, velocity, direction, acceleration, trajectory.
- Storage: keypoints in columnar files (Parquet) in object storage, with summary rows in Postgres. Do not store millions of keypoint rows in Postgres.
- Hand Tracking and Finger Tracking pages: overlay skeletons on video, per-finger velocity charts, missing-detection and tracking-failure stats.

**Acceptance criteria**
- Running tracking on a sample video produces visible, correct overlays.
- Swapping the adapter via config works without touching UI or API code.
- Every output row references a model version.

---

## PHASE 4 — Movement Classification & Object Interaction

**Goal:** Turn keypoints into meaningful, confidence-scored events.

**Build**
- Movement classes (editable, custom classes allowed): hand enters/exits frame, reach, grasp, release, pinch, point, tap, swipe, rotate, push, pull, pick up, put down, hold, move, manipulate, press, drag, gesture.
- Classifier adapter interface, same pattern as Phase 3. Start with a rule-based classifier using finger kinematics (e.g. pinch = thumb–index distance below threshold for N frames); allow a learned model later.
- Object detection adapter (e.g. YOLO) and hand–object contact detection.
- Event record: Event ID, Session ID, Video ID, start/end frame, start/end timestamp, class, hand, finger(s), object, confidence, model version, status (`auto_detected`, `needs_review`, `confirmed`, `rejected`, `corrected`).
- Interaction graph: Hand → Finger(s) → Movement → Object → Time range.
- Movement Classification and Object Tracking pages.

**Acceptance criteria**
- Events appear on the Phase 2 timeline automatically.
- Each event links back to the exact keypoint frames that produced it.

---

## PHASE 5 — Review & Active Learning

**Goal:** Efficient human correction, prioritising where the model is weakest.

**Build**
- Review page: accept / reject / correct auto annotations; corrections keep the original as a parent.
- Active-learning queue: sort review items by lowest confidence, highest model disagreement, and rarest class first.
- Metrics: human correction rate, per-class accuracy against human review, per-annotator throughput.
- Auto Annotation page: run auto-annotation on selected sessions with a chosen model version.

**Acceptance criteria**
- Correcting an event creates a new version and keeps the old one.
- The queue order visibly changes when confidence data changes.

---

## PHASE 6 — Datasets, Versioning & Lineage

**Goal:** Reproducible, exportable training datasets.

**Build**
- Dataset builder: filter by session, class, confidence, review status, quality flags, device, environment.
- Every dataset version stores: exact filters, included annotation IDs, model versions, and a content hash. Versions are immutable.
- Splits: train/val/test with options to split by session or operator (to avoid leakage).
- Exports: COCO, JSON Lines, Parquet, WebDataset, and a native Ego Labs format.
- Lineage graph view: click any exported sample to trace it back through annotations, model versions, processing jobs, and the raw frame.

**Acceptance criteria**
- Rebuilding a dataset version from its recorded spec gives an identical hash.
- Lineage view reaches the raw file from any sample.

---

## PHASE 7 — Pipelines

**Goal:** Composable, logged, schedulable processing.

**Build**
- Pipeline Builder: visual DAG of steps (ingest, extract frames, hand tracking, finger tracking, object detection, movement classification, quality checks, dataset build, export).
- Runs page: status per step, duration, logs, retries, failure reasons.
- Schedules (cron-style) and Templates.
- Quality-check steps: blur detection, low-light detection, occlusion rate, duplicate/near-duplicate detection.

**Acceptance criteria**
- A failed step can be retried without rerunning completed steps.
- Every run has complete, searchable logs.

---

## PHASE 8 — Models & Evaluation

**Build**
- Model Registry: every adapter version with config, metrics, and which datasets it was evaluated on.
- Inference page: run any registered model on selected videos.
- Evaluation: compare model versions against human-reviewed ground truth (precision, recall, F1 per class, keypoint error).
- Experiments page: record configurations and results side by side.

---

## PHASE 9 — Real-Time & Overview Command Center

**Build**
- Event Stream: live WebSocket feed of system events ("Session uploaded", "Hand tracking completed", "Movement detected: PICK_UP", "Human review required", "Dataset v14 created").
- Live Processing: active jobs, queue depth, processing FPS, inference latency.
- Infrastructure: worker health, GPU/CPU utilisation (from real worker telemetry).
- System Logs: searchable, filterable.
- Overview page with dataset stats, processing metrics, data quality metrics, and the live activity stream, all computed from real data.

**Acceptance criteria**
- Every Overview number can be clicked through to the records behind it.

---

## PHASE 10 — Mobile App (React Native / Expo)

**Scope (do not clone the web app):**
- Capture and upload video from the phone with session metadata.
- Review queue: accept/reject/correct events on short clips.
- Monitoring: job status and push notifications for failures and review requests.
- Read-only session and dataset browsing.

---

## PHASE 11 — Differentiators

These make Ego Labs unlike existing tools. Build after the core is stable.

1. **Human-to-robot retargeting export.** Map finger trajectories to robot hand and gripper kinematics (parallel gripper, multi-finger hands) with configurable embodiment profiles. Export ready-to-train action sequences.
2. **Manipulation query language.** Search like: `hand:right movement:pinch object:screw lighting:low confidence<0.8`, returning matching clips instantly.
3. **Skill discovery.** Cluster recurring movement patterns across sessions to suggest new movement classes nobody has defined yet.
4. **Data coverage map.** Show which combinations of movement × object × environment are over- or under-represented, to guide what to record next.
5. **Model disagreement view.** Run two model versions on the same video and highlight frames where they disagree.
