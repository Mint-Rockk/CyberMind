from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import (
    ATTACKTechnique,
    CTIDocument,
    CTISource,
    CorrelationRecord,
    DocumentEntityAssociation,
    ExtractedEntity,
    SourceType,
)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with Session(engine) as database_session:
        yield database_session
    Base.metadata.drop_all(engine)


def source() -> CTISource:
    return CTISource(
        name="Public Advisory Feed",
        source_type=SourceType.ADVISORY,
        base_url="https://example.test/advisories",
        configuration={},
    )


def document(source_id):
    return CTIDocument(
        source_id=source_id,
        canonical_key=f"document-{uuid4()}",
        title="Advisory",
        normalized_content="Normalized public CTI content.",
        document_status="normalized",
        retrieved_at=datetime.now(timezone.utc),
        provenance={"source": "fixture"},
    )


def test_document_and_entity_relationships(session: Session) -> None:
    cti_source = source()
    session.add(cti_source)
    session.flush()

    cti_document = document(cti_source.id)
    entity = ExtractedEntity(
        entity_type="malware",
        canonical_name="Example Malware",
        normalized_value="example-malware",
        attributes={},
    )
    session.add_all([cti_document, entity])
    session.flush()
    session.add(
        DocumentEntityAssociation(
            document_id=cti_document.id,
            entity_id=entity.id,
            mention_text="Example Malware",
        )
    )
    session.commit()

    result = session.scalar(select(CTIDocument).where(CTIDocument.id == cti_document.id))
    assert result is not None
    assert result.entity_associations[0].entity.normalized_value == "example-malware"


def test_unique_source_and_entity_constraints(session: Session) -> None:
    session.add(source())
    session.commit()
    session.add(source())

    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    entity = ExtractedEntity(
        entity_type="indicator",
        canonical_name="example.test",
        normalized_value="example.test",
        attributes={},
    )
    session.add(entity)
    session.commit()
    session.add(
        ExtractedEntity(
            entity_type="indicator",
            canonical_name="Example Test",
            normalized_value="example.test",
            attributes={},
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_correlation_record_stores_all_feature_dimensions(session: Session) -> None:
    cti_source = source()
    session.add(cti_source)
    session.flush()
    first = document(cti_source.id)
    second = document(cti_source.id)
    session.add_all([first, second])
    session.flush()

    record = CorrelationRecord(
        first_document_id=first.id,
        second_document_id=second.id,
        temporal_similarity=0.1,
        entity_relationship_similarity=0.2,
        behavioural_similarity=0.3,
        attack_technique_similarity=0.4,
        semantic_embedding_similarity=0.5,
        knowledge_graph_relationship_similarity=0.6,
        correlation_probability=0.7,
        prediction_threshold=0.65,
        predicted_relationship_label="related",
        predictor_type="baseline",
        predictor_version="baseline-1",
        feature_schema_version="features-1",
        evidence_and_explanation={"dimensions": ["temporal", "semantic"]},
    )
    session.add(record)
    session.commit()

    saved = session.get(CorrelationRecord, record.id)
    assert saved is not None
    assert saved.semantic_embedding_similarity == 0.5
    assert saved.knowledge_graph_relationship_similarity == 0.6
    assert saved.feature_schema_version == "features-1"
