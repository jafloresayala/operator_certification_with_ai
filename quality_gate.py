import cv2
import numpy as np
from biometric_models import QualityResult
from settings import SETTINGS

def estimate_brightness(image_bgr: np.ndarray) -> float:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    return float(np.mean(gray))

def estimate_blur_variance(image_bgr: np.ndarray) -> float:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())

def evaluate_quality(
    face_crop_bgr: np.ndarray,
    face_size_px: int,
    face_centered: bool,
    pose_ok: bool,
) -> QualityResult:
    brightness = estimate_brightness(face_crop_bgr)
    blur_var = estimate_blur_variance(face_crop_bgr)

    reasons = []

    if face_size_px < SETTINGS.MIN_FACE_SIZE_PX:
        reasons.append(f"Rostro demasiado pequeño: {face_size_px}px")

    if brightness < SETTINGS.MIN_BRIGHTNESS:
        reasons.append(f"Iluminación insuficiente: brillo={brightness:.1f}")

    if brightness > SETTINGS.MAX_BRIGHTNESS:
        reasons.append(f"Sobreexposición: brillo={brightness:.1f}")

    if blur_var < SETTINGS.MAX_BLUR_VARIANCE_THRESHOLD:
        reasons.append(f"Imagen borrosa: blur_var={blur_var:.1f}")

    if not face_centered:
        reasons.append("El rostro no está centrado en el marco.")

    if not pose_ok:
        reasons.append("La pose no es suficientemente frontal.")

    return QualityResult(
        passed=len(reasons) == 0,
        brightness=brightness,
        blur_variance=blur_var,
        face_size_px=face_size_px,
        face_centered=face_centered,
        pose_ok=pose_ok,
        reasons=reasons,
    )