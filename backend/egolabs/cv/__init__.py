"""
Computer vision (spec Phase 3): hand and finger tracking through swappable model adapters.

    frames (ffmpeg) → adapter.predict → tracking (persistent IDs) → One Euro smoothing
      → per-hand and per-finger kinematics → Parquet in object storage + summary rows in Postgres

Models plug in through `egolabs.cv.adapters.base.HandTrackingAdapter`; which one runs is configuration
(`HAND_TRACKING_ADAPTER`, `HAND_TRACKING_CONFIG`), never code in the API or UI.
"""
