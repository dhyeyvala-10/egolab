"""
One Euro filter (Casiez, Roussel & Vogel, CHI 2012): a low-pass filter whose cutoff rises with speed, so
keypoints are steady when the hand is still and follow closely when it moves.

Works on whole arrays at once (all 21 keypoints × x, y, z of one track), in pixel units so the default
parameters don't depend on the video's resolution.
"""

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class OneEuroConfig:
    min_cutoff: float = 1.2  # Hz: smoothing when still (lower = smoother, more lag)
    beta: float = 0.02  # how fast the cutoff rises with speed (higher = less lag when moving)
    d_cutoff: float = 1.0  # Hz: smoothing of the speed estimate itself


def _alpha(cutoff: float | np.ndarray, dt: float) -> float | np.ndarray:
    tau = 1.0 / (2 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


class OneEuroFilter:
    def __init__(self, config: OneEuroConfig | None = None) -> None:
        self.config = config or OneEuroConfig()
        self._x: np.ndarray | None = None
        self._dx: np.ndarray | None = None
        self._t: float | None = None

    def __call__(self, x: np.ndarray, t: float) -> np.ndarray:
        x = np.asarray(x, dtype=np.float64)
        if self._x is None or self._t is None or t <= self._t:
            self._x, self._dx, self._t = x.copy(), np.zeros_like(x), t
            return x.copy()
        dt = t - self._t
        cfg = self.config
        dx = (x - self._x) / dt
        a_d = _alpha(cfg.d_cutoff, dt)
        assert self._dx is not None
        dx_hat = a_d * dx + (1 - a_d) * self._dx
        cutoff = cfg.min_cutoff + cfg.beta * np.abs(dx_hat)
        a = _alpha(cutoff, dt)
        x_hat = a * x + (1 - a) * self._x
        self._x, self._dx, self._t = x_hat, dx_hat, t
        return x_hat
