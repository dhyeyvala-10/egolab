"""The CV code computes with numpy; its numbers must store in JSON columns like plain numbers."""

import numpy as np
from sqlalchemy import select

from egolabs.events import record_event
from egolabs.models import Event


def test_numpy_values_are_stored_as_plain_json(db):
    data = {"track": np.int64(7), "score": np.float32(0.5), "ok": np.bool_(True), "frames": np.arange(3),
            "nested": [{"n": np.int32(2)}]}  # fmt: skip
    record_event(db, "test.numpy", "numpy values", data=data)
    db.commit()
    db.expire_all()
    stored = db.scalar(select(Event).where(Event.type == "test.numpy")).data
    assert stored == {"track": 7, "score": 0.5, "ok": True, "frames": [0, 1, 2], "nested": [{"n": 2}]}
    assert type(stored["track"]) is int
