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
    get_all_enrolled_identities,
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

        # Extraer TODOS los rostros de la imagen
        all_extracted = engine.extract_all(frame_bgr)
        if not all_extracted:
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

        enrolled_embeddings = get_employee_samples(conn, employee_id, identity_id)
        if len(enrolled_embeddings) == 0:
            return VerificationResult(
                matched=False,
                identity_id=identity_id,
                employee_id=employee_id,
                distance=None,
                threshold_used=threshold,
                liveness=liveness_result,
                quality=all_extracted[0].quality,
                message="No hay plantillas enroladas para este empleado.",
            )

        # Probar CADA rostro detectado contra las plantillas del empleado
        best_result = None
        best_distance = float('inf')

        for extracted in all_extracted:
            result = engine.verify_one_to_one(
                probe_embedding=extracted.embedding,
                enrolled_embeddings=enrolled_embeddings,
                threshold=threshold,
                liveness=liveness_result,
            )

            # Guardar el mejor resultado (menor distancia)
            if result.distance is not None and result.distance < best_distance:
                best_distance = result.distance
                best_result = result
                best_result.quality = extracted.quality

            # Si alguno coincide, usar ese inmediatamente
            if result.matched:
                best_result = result
                best_result.quality = extracted.quality
                break

        if best_result is None:
            best_result = VerificationResult(
                matched=False,
                identity_id=identity_id,
                employee_id=employee_id,
                distance=None,
                threshold_used=threshold,
                liveness=liveness_result,
                quality=all_extracted[0].quality,
                message="No fue posible verificar ningún rostro.",
            )

        # completar ids
        best_result.employee_id = employee_id
        best_result.identity_id = identity_id

        log_verification(
            conn=conn,
            employee_id=employee_id,
            identity_id=identity_id,
            distance=best_result.distance,
            threshold_used=threshold,
            matched=best_result.matched,
            quality_json=best_result.quality.__dict__ if best_result.quality else {},
            liveness_json=liveness_result.__dict__ if liveness_result else {},
            source="streamlit_ui_1to1",
        )
        return best_result
    finally:
        conn.close()


def identify_faces_in_frame(
    engine: BiometricEngine,
    frame_bgr: np.ndarray,
    threshold: float,
) -> list:
    """
    Identificación 1:N — extrae TODOS los rostros del frame y los compara
    contra TODOS los empleados enrolados.

    Retorna lista de dicts, uno por cada rostro detectado:
        {
            "face_box": FaceBox,
            "matched": bool,
            "employee_number": str | None,
            "employee_name": str | None,
            "employee_id": int | None,
            "distance": float | None,
        }
    """
    all_extracted = engine.extract_all(frame_bgr)
    if not all_extracted:
        return []

    conn = get_db_connection()
    try:
        enrolled = get_all_enrolled_identities(conn)
        if not enrolled:
            # Nadie enrolado — devolver rostros sin identificar
            return [
                {
                    "face_box": ext.face_box,
                    "matched": False,
                    "employee_number": None,
                    "employee_name": None,
                    "employee_id": None,
                    "distance": None,
                }
                for ext in all_extracted
            ]

        results = []
        for ext in all_extracted:
            probe = ext.embedding
            probe_norm = probe / np.linalg.norm(probe)

            best_distance = float("inf")
            best_emp = None

            for emp in enrolled:
                for enrolled_emb in emp["embeddings"]:
                    enrolled_norm = enrolled_emb / np.linalg.norm(enrolled_emb)
                    similarity = float(np.dot(probe_norm, enrolled_norm))
                    distance = 1.0 - similarity
                    if distance < best_distance:
                        best_distance = distance
                        best_emp = emp

            matched = best_distance <= threshold and best_emp is not None

            results.append({
                "face_box": ext.face_box,
                "matched": matched,
                "employee_number": best_emp["employee_number"] if matched else None,
                "employee_name": best_emp["name"] if matched else None,
                "employee_id": best_emp["employee_id"] if matched else None,
                "distance": best_distance,
            })

        return results
    finally:
        conn.close()
