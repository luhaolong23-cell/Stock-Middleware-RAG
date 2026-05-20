from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import (
    DocumentArtifactResponse,
    DocumentResponse,
    IngestRequest,
    IngestResponse,
)
from app.core.database import get_db
from app.ingestion.pipeline import IngestionPipeline
from app.services.artifact_service import ArtifactService
from app.services.doc_service import DocService

router = APIRouter(prefix="/docs", tags=["docs"])


@router.post("/ingest", response_model=IngestResponse)
def ingest_document(
    request: IngestRequest, db: Session = Depends(get_db)
) -> IngestResponse:
    pipeline = IngestionPipeline(db)
    try:
        result = pipeline.run(request.file_path, overwrite=request.overwrite)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return IngestResponse(**result)


@router.get("", response_model=list[DocumentResponse])
def list_documents(db: Session = Depends(get_db)) -> list[DocumentResponse]:
    service = DocService(db)
    documents = service.list_documents()
    return [DocumentResponse(**doc) for doc in documents]


@router.get("/{document_id}/artifacts", response_model=list[DocumentArtifactResponse])
def list_document_artifacts(
    document_id: int,
    db: Session = Depends(get_db),
) -> list[DocumentArtifactResponse]:
    doc_service = DocService(db)
    document = doc_service.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail=f"document {document_id} not found")

    artifact_service = ArtifactService(db)
    artifacts = artifact_service.list_document_artifacts(document_id)
    return [DocumentArtifactResponse(**item) for item in artifacts]
