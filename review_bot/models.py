from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


@dataclass
class Review:
    platform: str
    account: str
    author: str
    rating: int | None
    text: str
    order_count: int | None = None
    has_photo: bool = False
    date_text: str = ""

    @property
    def key(self) -> str:
        """같은 리뷰를 다시 찾을 때 쓰는 고유값 (확인대기.xlsx 매칭용)."""
        raw = "|".join(
            [self.platform, self.account, self.author, self.date_text, normalize(self.text)[:100]]
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
