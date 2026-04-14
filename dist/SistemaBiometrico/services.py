import os
import cv2
import numpy as np
from typing import Optional, Dict, Any
from datetime import datetime

from settings import SETTINGS
from repository import (
    get_db_connection,
    create_identity,
    create_employee,
    add_identity_sample,
    get_employee_by_number,
    get_employee_samples,
    log_verification,
)
from biometric_engine import BiometricEngine
from biometric_models import VerificationResult, LivenessResult

def datetime_stamp() -> str:
    """Genera un timestamp formateado para nombres de archivo."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def ensure_ref_dir():
    if not os.path.exists(SETTINGS.REF_IMAGES_DIR):
        os.makedirs(SETTINGS.REF_IMAGES_DIR, exist_ok=True)

def enroll_sample_for_employee(
    engine: BiometricEngine,
    employee_data: Dict[str, Any],
    frame_bgr: np.ndarray,
    sample_tag: str = "",
    glasses: bool = False,
    lighting_tag: str = "",
    pose_tag: str = "",
):
    ensure_ref_dir()

    extracted = engine.extract(frame_bgr)
    if extracted is None:
        return False, "No fue posible extraer rostro/alineación/embedding.", None

    if not extracted.quality.passed:
        return False, f"Quality gate falló: {' | '.join(extracted.quality.reasons)}", None

    conn = get_db_connection()
    try:
        row = get_employee_by_number(conn, employee_data["employee_number"])

        if row is None:
            identity_id = create_identity(conn, extracted.embedding)
            employee_id = create_employee(conn, employee_data, identity_id)
        else:
            employee_id = int(row["id"])
            identity_id = int(row["face_identity_id"])

        image_name = (
            f"{employee_data['employee_number']}_"
            f"{sample_tag or 'sample'}_{datetime_stamp()}.jpg"
        )
        image_path = os.path.join(SETTINGS.REF_IMAGES_DIR, image_name)
        cv2.imwrite(image_path, extracted.aligned_face_bgr)

        sample_id = add_identity_sample(
            conn=conn,
            identity_id=identity_id,
            employee_id=employee_id,
            embedding=extracted.embedding,
            quality=extracted.quality.__dict__,
            image_path=image_path,
            sample_tag=sample_tag,
            glasses=glasses,
            lighting_tag=lighting_tag,
            pose_tag=pose_tag,
        )

        return True, "Muestra registrada correctamente.", {
            "employee_id": employee_id,
            "identity_id": identity_id,
            "sample_id": sample_id,
            "quality": extracted.quality.__dict__,
        }
    finally:
        conn.close()

def verify_employee_one_to_one(
    engine: BiometricEngine,
    employee_number: str,
    frame_bgr: np.ndarray,
    threshold: float,
    liveness_result: Optional[LivenessResult] = None,
) -> VerificationResult:
    conn = get_db_connection()
    try:
        employee = get_employee_by_number(conn, employee_number)
        if employee is None:
            return VerificationResult(
                matched=False,
                identity_id=None,
                employee_id=None,
                distance=None,
                threshold_used=threshold,
                liveness=liveness_result,
                quality=None,
                message="Número de empleado no encontrado.",
            )

        employee_id = int(employee["id"])
        identity_id = int(employee["face_identity_id"]) if employee["face_identity_id"] else None

        extracted = engine.extract(frame_bgr)
        if extracted is None:
            return VerificationResult(
                matched=False,
                identity_id=identity_id,
                employee_id=employee_id,
                distance=None,
                threshold_used=threshold,
                liveness=liveness_result,
                quality=None,
                message="No fue posible extraer un rostro válido.",
            )

        if not extracted.quality.passed:
            return VerificationResult(
                matched=False,
                identity_id=identity_id,
                employee_id=employee_id,
                distance=None,
                threshold_used=threshold,
                liveness=liveness_result,
                quality=extracted.quality,
                message="La captura no pasó el quality gate.",
            )

        enrolled_embeddings = get_employee_samples(conn, employee_id, identity_id)
        if len(enrolled_embeddings) == 0:
            return VerificationResult(
                matched=False,
                identity_id=identity_id,
                employee_id=employee_id,
                distance=None,
                threshold_used=threshold,
                liveness=liveness_result,
                quality=extracted.quality,
                message="No hay plantillas enroladas para este empleado.",
            )

        result = engine.verify_one_to_one(
            probe_embedding=extracted.embedding,
            enrolled_embeddings=enrolled_embeddings,
            threshold=threshold,
            liveness=liveness_result,
        )

        # completar ids
        result.employee_id = employee_id
        result.identity_id = identity_id
        result.quality = extracted.quality

        log_verification(
            conn=conn,
            employee_id=employee_id,
            identity_id=identity_id,
            distance=result.distance,
            threshold_used=threshold,
            matched=result.matched,
            quality_json=extracted.quality.__dict__ if extracted.quality else {},
            liveness_json=liveness_result.__dict__ if liveness_result else {},
            source="streamlit_ui_1to1",
        )
        return result
    finally:
        conn.close()
