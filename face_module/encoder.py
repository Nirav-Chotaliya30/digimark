import base64
from typing import Tuple

import cv2
import face_recognition
import numpy as np


class FaceEncodingError(Exception):
    pass


def decode_base64_to_image(base64_data: str) -> np.ndarray:
    try:
        payload = base64_data.split(",", 1)[1] if "," in base64_data else base64_data
        img_bytes = base64.b64decode(payload)
        np_arr = np.frombuffer(img_bytes, dtype=np.uint8)
        bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if bgr is None:
            raise FaceEncodingError("Invalid image data.")
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    except Exception as exc:
        raise FaceEncodingError(f"Could not decode image: {exc}") from exc


def _single_face_location(rgb_image: np.ndarray) -> Tuple[int, int, int, int]:
    locations = face_recognition.face_locations(rgb_image, model="hog")
    if len(locations) == 0:
        raise FaceEncodingError("No face detected.")
    if len(locations) > 1:
        raise FaceEncodingError("Multiple faces detected. Please be alone in frame.")
    return locations[0]


def extract_face_location(rgb_image: np.ndarray) -> Tuple[int, int, int, int]:
    return _single_face_location(rgb_image)


def extract_face_encoding(rgb_image: np.ndarray) -> np.ndarray:
    location = _single_face_location(rgb_image)
    encodings = face_recognition.face_encodings(rgb_image, known_face_locations=[location], num_jitters=1)
    if not encodings:
        raise FaceEncodingError("Face encoding failed.")
    return encodings[0]
