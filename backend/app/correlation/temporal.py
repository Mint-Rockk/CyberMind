from datetime import datetime, timezone
from typing import Any

from app.correlation.types import FeatureResult
from app.correlation.utils import representation


def _window(document: Any) -> tuple[datetime, datetime] | None:
    item = representation(document)
    start = item.activity_start or item.published_at
    end = item.activity_end or item.published_at
    if start is None or end is None:
        return None
    start = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
    end = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
    return min(start, end), max(start, end)


def temporal_similarity(first: Any, second: Any) -> FeatureResult:
    left, right = _window(first), _window(second)
    if left is None or right is None:
        return FeatureResult("temporal_similarity", 0.5, False, {
            "status": "missing", "reason": "both documents need publication or activity timestamps",
        })
    overlap = max(0.0, (min(left[1], right[1]) - max(left[0], right[0])).total_seconds())
    union = (max(left[1], right[1]) - min(left[0], right[0])).total_seconds()
    score = 1.0 if union == 0 else overlap / union
    return FeatureResult("temporal_similarity", score, True, {
        "status": "observed", "left_window": [left[0].isoformat(), left[1].isoformat()],
        "right_window": [right[0].isoformat(), right[1].isoformat()], "overlap_seconds": overlap,
    })
