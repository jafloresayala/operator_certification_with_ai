from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import numpy as np

@dataclass
class FaceBox:
    top: int
    right: int
    bottom: int
    left: int

@dataclass
class QualityResult:
    passed: bool
    brightness: float
    blur_variance: float
    face_size_px: int
    face_centered: bool
    pose_ok: bool
    reasons: List[str] = field(default_factory=list)

@dataclass
class LivenessResult:
    passed: bool
    score: float
    method: str
    reasons: List[str] = field(default_factory=list)

@dataclass
class ExtractedFace:
    aligned_face_bgr: np.ndarray
    face_box: FaceBox
    embedding: np.ndarray
    quality: QualityResult

@dataclass
class VerificationResult:
    matched: bool
    identity_id: Optional[int]
    employee_id: Optional[int]
    distance: Optional[float]
    threshold_used: float
    liveness: Optional[LivenessResult]
    quality: Optional[QualityResult]
    message: str
