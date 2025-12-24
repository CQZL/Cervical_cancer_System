from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import torch


@dataclass
class Tile:
    image: np.ndarray
    x0: int
    y0: int


@dataclass
class Det:
    bbox: np.ndarray  # (x1, y1, x2, y2) in tile coordinates
    score: float
    cls: int
    tile_x0: int
    tile_y0: int


@dataclass
class Instance:
    feat: torch.Tensor
    prob: torch.Tensor
    coord_global: Tuple[int, int]
    det_score: float
    bbox_global: Tuple[float, float, float, float]
    patch: Optional[np.ndarray] = None
