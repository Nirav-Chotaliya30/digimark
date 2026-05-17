import csv
import io
import math
from datetime import date, datetime
from typing import Iterable, Tuple


def calculate_haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lng2 - lng1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius * c


def calculate_attendance_percentage(total: int, present: int) -> float:
    if total <= 0:
        return 0.0
    return round((present / total) * 100, 2)


def check_basic_liveness(face_locations: Iterable[Tuple[int, int, int, int]], min_shift: int = 8) -> bool:
    points = list(face_locations)
    if len(points) < 3:
        return False
    centers = [((l[1] + l[3]) / 2.0, (l[0] + l[2]) / 2.0) for l in points]
    x_values = [c[0] for c in centers]
    y_values = [c[1] for c in centers]
    return (max(x_values) - min(x_values) >= min_shift) or (max(y_values) - min(y_values) >= min_shift)


def normalize_date_range(start_date: str, end_date: str) -> tuple[date | None, date | None]:
    def parse(value: str | None):
        if not value:
            return None
        return datetime.strptime(value, "%Y-%m-%d").date()

    return parse(start_date), parse(end_date)


def attendance_rows_to_csv(rows: list[dict]) -> io.BytesIO:
    stream = io.StringIO()
    writer = csv.DictWriter(
        stream,
        fieldnames=[
            "attendance_id",
            "student_id",
            "student_name",
            "enrollment_no",
            "subject_code",
            "subject_name",
            "date",
            "time",
            "status",
            "face_verified",
            "gps_verified",
            "latitude",
            "longitude",
        ],
    )
    writer.writeheader()
    writer.writerows(rows)
    bytes_stream = io.BytesIO()
    bytes_stream.write(stream.getvalue().encode("utf-8"))
    bytes_stream.seek(0)
    return bytes_stream
