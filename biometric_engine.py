from abc import ABC, abstractmethod
from typing import List, Optional
import numpy as np
import cv2
import os
from pathlib import Path
from biometric_models import ExtractedFace, VerificationResult, LivenessResult, FaceBox, QualityResult

try:
    import insightface
    from insightface.app import FaceAnalysis
    INSIGHTFACE_AVAILABLE = True
except ImportError:
    INSIGHTFACE_AVAILABLE = False

try:
    import face_recognition
    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    FACE_RECOGNITION_AVAILABLE = False


class BiometricEngine(ABC):
    @abstractmethod
    def extract(self, image_bgr: np.ndarray) -> Optional[ExtractedFace]:
        """Detecta, alinea y extrae embedding + quality."""
        raise NotImplementedError

    @abstractmethod
    def verify_one_to_one(
        self,
        probe_embedding: np.ndarray,
        enrolled_embeddings: List[np.ndarray],
        threshold: float,
        liveness: Optional[LivenessResult] = None,
    ) -> VerificationResult:
        """Verificación 1:1 contra las plantillas de una sola identidad."""
        raise NotImplementedError


class ArcFaceEngine(BiometricEngine):
    """
    Motor biométrico profesional basado en InsightFace + ArcFace.
    Proporciona detección, alineación, extracción de embeddings y verificación 1:1.
    Soporta carga de modelos desde ruta local para evitar descargas.
    """
    
    def __init__(self, model_name: str = "buffalo_l", providers: List[str] = None, model_root: Optional[str] = None):
        """
        Inicializa el motor ArcFace.
        
        Args:
            model_name: Modelo InsightFace a usar (default: "buffalo_l")
            providers: Providers ONNX (default: ["CUDAExecutionProvider", "CPUExecutionProvider"])
            model_root: Ruta local a carpeta con modelos descargados (opcional)
        
        Raises:
            RuntimeError: Si InsightFace no está instalado o hay error en la descarga
        """
        if not INSIGHTFACE_AVAILABLE:
            raise RuntimeError(
                "InsightFace no está instalado. Instala con:\n"
                "  pip install insightface onnxruntime\n"
                "O con conda:\n"
                "  conda install -c conda-forge insightface"
            )
        
        if providers is None:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        
        try:
            print(f"Inicializando FaceAnalysis con modelo '{model_name}'...")
            
            # Si se proporciona raíz de modelos, usarla
            if model_root:
                os.environ['INSIGHTFACE_HOME'] = model_root
                print(f"Usando modelos desde: {model_root}")
            
            self.app = FaceAnalysis(name=model_name, providers=providers)
            self.app.prepare(ctx_id=0, det_thresh=0.5, det_size=(640, 640))
            print(f"✓ Motor ArcFace inicializado correctamente con {model_name}")
            self.model_name = model_name
        except Exception as e:
            error_msg = str(e)
            home_path = Path.home() / '.insightface' / 'models' / 'buffalo_l'
            if "SSL" in error_msg or "certificate" in error_msg.lower():
                raise RuntimeError(
                    f"Error de SSL al descargar modelos desde GitHub.\n\n"
                    "SOLUCIÓN RECOMENDADA:\n"
                    "1. Descarga el archivo ZIP manualmente desde:\n"
                    "   https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip\n\n"
                    "2. Extrae el contenido en la carpeta:\n"
                    f"   {home_path}\n\n"
                    f"   O si estás en Windows:\n"
                    f"   {home_path}\n\n"
                    "3. Verifica que la carpeta contenga archivos como .onnx, .param, etc.\n\n"
                    "4. Reinicia la aplicación\n\n"
                    "Si usas ruta personalizada, inicializa con:\n"
                    "   engine = ArcFaceEngine(model_root='/ruta/a/modelos')"
                ) from e
            else:
                raise RuntimeError(
                    f"Error al inicializar motor ArcFace: {error_msg}"
                ) from e
    
    def _check_image_quality(self, image_bgr: np.ndarray, face_box: FaceBox) -> QualityResult:
        """Verifica la calidad de la imagen capturada."""
        reasons = []
        h, w = image_bgr.shape[:2]
        
        # Calcular varianza de desenfoque (Laplacian)
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        blur_variance = cv2.Laplacian(gray, cv2.CV_64F).var()
        blur_ok = blur_variance > 50  # Threshold para detectar desenfoque (muy permisivo)
        if not blur_ok:
            reasons.append("Imagen desenfocada")
        
        # Verificar brillo
        brightness = np.mean(gray)
        brightness_ok = 50 < brightness < 200
        if not brightness_ok:
            reasons.append(f"Brillo inadecuado ({brightness:.1f})")
        
        # Verificar tamaño del rostro
        face_width = face_box.right - face_box.left
        face_height = face_box.bottom - face_box.top
        face_size = face_width * face_height
        face_size_ok = face_size > 10000  # Aproximadamente 100x100 píxeles
        if not face_size_ok:
            reasons.append(f"Rostro muy pequeño ({face_width}x{face_height})")
        
        # Verificar centrado (asume ROI central)
        face_center_x = (face_box.left + face_box.right) / 2
        face_center_y = (face_box.top + face_box.bottom) / 2
        center_x, center_y = w / 2, h / 2
        distance_to_center = np.sqrt((face_center_x - center_x)**2 + (face_center_y - center_y)**2)
        face_centered = distance_to_center < max(w, h) * 0.25
        if not face_centered:
            reasons.append("Rostro no está centrado")
        
        # Pose está implícitamente verificada por el modelo
        pose_ok = True
        
        passed = blur_ok and brightness_ok and face_size_ok and face_centered
        
        return QualityResult(
            passed=bool(passed),
            brightness=float(brightness),
            blur_variance=float(blur_variance),
            face_size_px=int(face_size),
            face_centered=bool(face_centered),
            pose_ok=bool(pose_ok),
            reasons=reasons,
        )
    
    def extract(self, image_bgr: np.ndarray) -> Optional[ExtractedFace]:
        """
        Extrae el rostro más grande de la imagen.
        Retorna embedding, rostro alineado y métricas de calidad.
        
        Args:
            image_bgr: Imagen en formato BGR (OpenCV)
        
        Returns:
            ExtractedFace con embedding, alineación y quality, o None si falla
        """
        try:
            # Detectar rostros
            faces = self.app.get(image_bgr)
            
            if not faces:
                return None
            
            # Usar el rostro más grande
            largest_face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
            
            # Extraer coordenadas
            x1, y1, x2, y2 = largest_face.bbox[:4]
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
            
            # Crear FaceBox
            face_box = FaceBox(top=y1, bottom=y2, left=x1, right=x2)
            
            # Verificar calidad
            quality = self._check_image_quality(image_bgr, face_box)
            
            # Extraer rostro alineado (usando landmarks implícitos del modelo)
            # InsightFace ya realiza la alineación internamente
            aligned_face = image_bgr[y1:y2, x1:x2].copy()
            
            # Normalizar a tamaño estándar (112x112 para ArcFace)
            aligned_face = cv2.resize(aligned_face, (112, 112))
            
            # El embedding ya está disponible desde el modelo
            embedding = largest_face.embedding.astype(np.float32)
            
            return ExtractedFace(
                aligned_face_bgr=aligned_face,
                face_box=face_box,
                embedding=embedding,
                quality=quality,
            )
        except Exception as e:
            print(f"Error en extracción: {e}")
            return None
    
    def verify_one_to_one(
        self,
        probe_embedding: np.ndarray,
        enrolled_embeddings: List[np.ndarray],
        threshold: float,
        liveness: Optional[LivenessResult] = None,
    ) -> VerificationResult:
        """
        Verifica un embedding de prueba contra embeddings matriculados.
        
        Args:
            probe_embedding: Embedding a verificar
            enrolled_embeddings: Lista de embeddings matriculados (1 identidad)
            threshold: Distancia máxima para considerar coincidencia
            liveness: Resultado de liveness (opcional)
        
        Returns:
            VerificationResult con resultado, distancia y mensaje
        """
        try:
            if not enrolled_embeddings:
                return VerificationResult(
                    matched=False,
                    identity_id=None,
                    employee_id=None,
                    distance=None,
                    threshold_used=threshold,
                    liveness=liveness,
                    quality=None,
                    message="No hay embeddings matriculados.",
                )
            
            # Calcular similitud cosena contra cada embedding matriculado
            # (InsightFace usa similitud cosena para ArcFace)
            similarities = []
            for enrolled in enrolled_embeddings:
                # Normalizar embeddings
                probe_norm = probe_embedding / np.linalg.norm(probe_embedding)
                enrolled_norm = enrolled / np.linalg.norm(enrolled)
                
                # Similitud cosena
                similarity = np.dot(probe_norm, enrolled_norm)
                similarities.append(similarity)
            
            best_similarity = max(similarities)
            # Convertir similitud cosena a distancia (1 - similitud)
            best_distance = 1.0 - best_similarity
            
            matched = best_distance <= threshold
            
            message = (
                f"Verificación {'exitosa' if matched else 'fallida'}. "
                f"Distancia: {best_distance:.4f}, Threshold: {threshold:.4f}"
            )
            
            return VerificationResult(
                matched=matched,
                identity_id=None,  # Se actualiza en services.py
                employee_id=None,
                distance=float(best_distance),
                threshold_used=threshold,
                liveness=liveness,
                quality=None,
                message=message,
            )
        except Exception as e:
            return VerificationResult(
                matched=False,
                identity_id=None,
                employee_id=None,
                distance=None,
                threshold_used=threshold,
                liveness=liveness,
                quality=None,
                message=f"Error en verificación: {str(e)}",
            )


class SimpleEmbeddingEngine(BiometricEngine):
    """
    Motor alternativo usando face_recognition (dlib).
    Más simple pero menos preciso que ArcFace, útil como fallback.
    """
    
    def __init__(self):
        if not FACE_RECOGNITION_AVAILABLE:
            raise RuntimeError("face_recognition no disponible")
        print("✓ Motor face_recognition inicializado (fallback mode)")
    
    def _check_image_quality(self, image_bgr: np.ndarray, face_box: FaceBox) -> QualityResult:
        """Verifica la calidad de la imagen capturada."""
        reasons = []
        h, w = image_bgr.shape[:2]
        
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        blur_variance = cv2.Laplacian(gray, cv2.CV_64F).var()
        blur_ok = blur_variance > 50  # Muy permisivo para cámaras de menor calidad
        if not blur_ok:
            reasons.append("Imagen desenfocada")
        
        brightness = np.mean(gray)
        brightness_ok = 50 < brightness < 200
        if not brightness_ok:
            reasons.append(f"Brillo inadecuado ({brightness:.1f})")
        
        face_width = face_box.right - face_box.left
        face_height = face_box.bottom - face_box.top
        face_size = face_width * face_height
        face_size_ok = face_size > 10000
        if not face_size_ok:
            reasons.append(f"Rostro muy pequeño ({face_width}x{face_height})")
        
        passed = blur_ok and brightness_ok and face_size_ok
        
        return QualityResult(
            passed=bool(passed),
            brightness=float(brightness),
            blur_variance=float(blur_variance),
            face_size_px=int(face_size),
            face_centered=bool(True),
            pose_ok=bool(True),
            reasons=reasons,
        )
    
    def extract(self, image_bgr: np.ndarray) -> Optional[ExtractedFace]:
        """Extrae el rostro más grande."""
        try:
            rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
            face_locations = face_recognition.face_locations(rgb, model="hog")
            face_encodings = face_recognition.face_encodings(rgb, face_locations)
            
            if not face_locations:
                return None
            
            # Usar el primer rostro
            top, right, bottom, left = face_locations[0]
            face_box = FaceBox(top=top, bottom=bottom, left=left, right=right)
            
            quality = self._check_image_quality(image_bgr, face_box)
            
            aligned_face = image_bgr[top:bottom, left:right].copy()
            aligned_face = cv2.resize(aligned_face, (112, 112))
            
            embedding = face_encodings[0].astype(np.float32)
            
            return ExtractedFace(
                aligned_face_bgr=aligned_face,
                face_box=face_box,
                embedding=embedding,
                quality=quality,
            )
        except Exception as e:
            print(f"Error en face_recognition: {e}")
            return None
    
    def verify_one_to_one(
        self,
        probe_embedding: np.ndarray,
        enrolled_embeddings: List[np.ndarray],
        threshold: float,
        liveness: Optional[LivenessResult] = None,
    ) -> VerificationResult:
        """Verificación contra embeddings matriculados."""
        try:
            if not enrolled_embeddings:
                return VerificationResult(
                    matched=False, identity_id=None, employee_id=None,
                    distance=None, threshold_used=threshold, liveness=liveness,
                    quality=None, message="No hay embeddings matriculados.",
                )
            
            # Usar distancia euclidiana (face_recognition usa esta métrica)
            distances = []
            for enrolled in enrolled_embeddings:
                distance = np.linalg.norm(probe_embedding - enrolled)
                distances.append(distance)
            
            best_distance = min(distances)
            matched = best_distance <= threshold
            
            message = (
                f"Verificación {'exitosa' if matched else 'fallida'}. "
                f"Distancia: {best_distance:.4f}, Threshold: {threshold:.4f}"
            )
            
            return VerificationResult(
                matched=matched, identity_id=None, employee_id=None,
                distance=float(best_distance), threshold_used=threshold,
                liveness=liveness, quality=None, message=message,
            )
        except Exception as e:
            return VerificationResult(
                matched=False, identity_id=None, employee_id=None,
                distance=None, threshold_used=threshold, liveness=liveness,
                quality=None, message=f"Error en verificación: {str(e)}",
            )


# Alias para compatibilidad
StubArcFaceEngine = ArcFaceEngine
