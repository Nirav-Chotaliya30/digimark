from typing import Iterable

import face_recognition
import numpy as np


def compare_face_encodings(stored_encoding: Iterable[float], live_encoding: np.ndarray, tolerance: float = 0.5) -> dict:
    known = np.array(stored_encoding, dtype=np.float64)
    if known.shape != (128,):
        raise ValueError("Stored face encoding is invalid.")

    if live_encoding.shape != (128,):
        raise ValueError("Live face encoding is invalid.")

    distance = float(face_recognition.face_distance([known], live_encoding)[0])
    match = distance <= tolerance
    confidence = max(0.0, min(1.0, 1.0 - distance))

    return {
        "match": match,
        "distance": round(distance, 4),
        "confidence": round(confidence, 4),
        "tolerance": tolerance,
    }
