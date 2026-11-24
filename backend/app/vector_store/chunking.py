from dataclasses import dataclass
import re
from uuid import UUID, uuid5, NAMESPACE_URL


_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class DocumentChunk:
    chunk_id: str
    document_id: UUID
    index: int
    text: str


def split_document(
    document_id: UUID,
    text: str,
    *,
    max_characters: int = 1200,
    overlap_characters: int = 150,
) -> list[DocumentChunk]:
    if max_characters < 1:
        raise ValueError("max_characters must be positive")
    if overlap_characters < 0 or overlap_characters >= max_characters:
        raise ValueError("overlap_characters must be non-negative and smaller than max_characters")
    cleaned = " ".join(text.split())
    if not cleaned:
        return []

    sentences = _SENTENCE_BOUNDARY.split(cleaned)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > max_characters:
            chunks.append(current)
            overlap = current[-overlap_characters:] if overlap_characters else ""
            current = f"{overlap} {sentence}".strip()
        elif len(candidate) > max_characters:
            for start in range(0, len(sentence), max_characters - overlap_characters):
                piece = sentence[start:start + max_characters]
                chunks.append(piece.strip())
            current = ""
        else:
            current = candidate
    if current:
        chunks.append(current)

    return [
        DocumentChunk(
            chunk_id=str(uuid5(NAMESPACE_URL, f"cybermind:{document_id}:{index}:{chunk}")),
            document_id=document_id,
            index=index,
            text=chunk,
        )
        for index, chunk in enumerate(chunks)
        if chunk
    ]
