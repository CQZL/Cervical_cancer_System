import logging
from dataclasses import dataclass
from typing import List

import numpy as np
import torch
from torchvision import transforms
from torchvision.models import convnext_tiny, convnext_small, convnext_base, convnext_large

logger = logging.getLogger(__name__)


ARCH_FACTORY = {
    "convnext_tiny": convnext_tiny,
    "convnext_small": convnext_small,
    "convnext_base": convnext_base,
    "convnext_large": convnext_large,
}


@dataclass
class EncoderConfig:
    arch: str = "convnext_tiny"
    num_classes: int = 2
    mean: List[float] = None
    std: List[float] = None
    positive_index: int = 1


class ConvNeXtEncoder:
    def __init__(self, ckpt_path: str, device: str, config: EncoderConfig) -> None:
        if config.mean is None:
            config.mean = [0.485, 0.456, 0.406]
        if config.std is None:
            config.std = [0.229, 0.224, 0.225]
        if config.arch not in ARCH_FACTORY:
            raise ValueError(f"Unsupported convnext arch: {config.arch}")
        if "cuda" in device and not torch.cuda.is_available():
            logger.warning("CUDA not available, falling back to CPU for encoder")
            device = "cpu"
        self.device = torch.device(device)
        self.config = config
        self.model = ARCH_FACTORY[config.arch](num_classes=config.num_classes)
        self._load_checkpoint(ckpt_path)
        self.model.to(self.device)
        self.model.eval()
        self.transform = transforms.Compose(
            [
                transforms.ToTensor(),
                transforms.Normalize(mean=config.mean, std=config.std),
            ]
        )
        self.feature_dim = self.model.classifier[1].in_features

    def _load_checkpoint(self, ckpt_path: str) -> None:
        checkpoint = torch.load(ckpt_path, map_location="cpu")
        if isinstance(checkpoint, dict):
            state_dict = checkpoint.get("state_dict") or checkpoint.get("model_state_dict")
            if state_dict is None:
                state_dict = checkpoint
        else:
            state_dict = checkpoint
        cleaned = {k.replace("module.", ""): v for k, v in state_dict.items()}
        missing, unexpected = self.model.load_state_dict(cleaned, strict=False)
        if missing:
            logger.warning("Encoder missing keys: %s", missing)
        if unexpected:
            logger.warning("Encoder unexpected keys: %s", unexpected)

    @torch.inference_mode()
    def encode(self, patches: List[np.ndarray]):
        if not patches:
            return (
                torch.empty((0, self.feature_dim), dtype=torch.float32),
                torch.empty((0,), dtype=torch.float32),
            )
        tensors = torch.stack([self.transform(patch) for patch in patches]).to(self.device)
        features = self.model.features(tensors)
        pooled = self.model.avgpool(features)
        pooled = torch.flatten(pooled, 1)
        logits = self.model.classifier(pooled)
        if self.config.num_classes > 1:
            probs = torch.softmax(logits, dim=1)[:, self.config.positive_index]
        else:
            probs = torch.sigmoid(logits.squeeze(1))
        return pooled.detach().cpu(), probs.detach().cpu()
