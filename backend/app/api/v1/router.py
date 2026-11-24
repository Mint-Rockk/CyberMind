from fastapi import APIRouter

from app.api.v1.health import router as health_router
from app.api.v1.ingestion import router as ingestion_router
from app.api.v1.sources import router as sources_router
from app.api.v1.documents import router as documents_router
from app.api.v1.entities import router as entities_router
from app.api.v1.attack import router as attack_router
from app.api.v1.correlations import router as correlations_router
from app.api.v1.campaigns import router as campaigns_router
from app.api.v1.graph import router as graph_router
from app.api.v1.vector import router as vector_router
from app.api.v1.rag import router as rag_router
from app.api.v1.investigations import router as investigations_router
from app.api.v1.assistant import router as assistant_router
from app.api.v1.reports import router as reports_router
from app.api.v1.reviews import router as reviews_router
from app.api.v1.audit import router as audit_router
from app.api.v1.model import router as model_router
from app.api.v1.dashboard import router as dashboard_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
router.include_router(sources_router)
router.include_router(ingestion_router)
router.include_router(documents_router)
router.include_router(entities_router)
router.include_router(attack_router)
router.include_router(correlations_router)
router.include_router(campaigns_router)
router.include_router(graph_router)
router.include_router(vector_router)
router.include_router(rag_router)
router.include_router(investigations_router)
router.include_router(assistant_router)
router.include_router(reports_router)
router.include_router(reviews_router)
router.include_router(audit_router)
router.include_router(model_router)
router.include_router(dashboard_router)
