import logging
from dataclasses import dataclass
from typing import Generator, Optional, Tuple

import importlib
import numpy as np


openslide_spec = importlib.util.find_spec("openslide")
if openslide_spec is None:
    raise ImportError(
        "openslide-python is required to read WSI files. "
        "Please install openslide and openslide-python."
    )

openslide = importlib.import_module("openslide")
OpenSlide = openslide.OpenSlide
OpenSlideError = openslide.OpenSlideError

from .types import Tile

logger = logging.getLogger(__name__)


@dataclass
class WSIConfig:
    tile_size: int = 2048
    stride: int = 2048
    level: int = 0
    downsample: Optional[float] = None


class WSIReader:
    def __init__(self, wsi_path: str, config: WSIConfig) -> None:
        self.wsi_path = wsi_path
        try:
            self.slide = OpenSlide(wsi_path)
        except OpenSlideError as exc:
            raise RuntimeError(
                f"Failed to open WSI: {wsi_path}. "
                "Please check file format and openslide installation."
            ) from exc
        self.config = config
        self.level = self._resolve_level()
        self.downsample = float(self.slide.level_downsamples[self.level])
        self.level_dims = self.slide.level_dimensions[self.level]

    def _resolve_level(self) -> int:
        if self.config.downsample is not None:
            level = self.slide.get_best_level_for_downsample(self.config.downsample)
            logger.info("Using level %s for downsample %s", level, self.config.downsample)
            return level
        return self.config.level

    def iter_tiles(self) -> Generator[Tile, None, None]:
        tile_size = self.config.tile_size
        stride = self.config.stride
        width, height = self.level_dims
        for y in range(0, height, stride):
            for x in range(0, width, stride):
                read_x = int(x * self.downsample)
                read_y = int(y * self.downsample)
                region = self.slide.read_region((read_x, read_y), self.level, (tile_size, tile_size))
                rgb = np.array(region.convert("RGB"))
                yield Tile(image=rgb, x0=read_x, y0=read_y)

    def get_slide_id(self) -> str:
        return self.wsi_path.split("/")[-1].split(".")[0]

    def close(self) -> None:
        self.slide.close()
