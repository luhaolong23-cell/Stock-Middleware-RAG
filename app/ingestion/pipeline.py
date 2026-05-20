from __future__ import annotations

from sqlalchemy.orm import Session

from app.ingestion.chunker_unstructured import FinancialReportChunkerV2
from app.ingestion.cleaner import TextCleaner
from app.ingestion.extractor import MetadataExtractor
from app.ingestion.parser import DocumentParser, ParsedElement
from app.retrieval.bm25 import lexical_tokenize
from app.retrieval.embedder import SimpleEmbedder, build_embedding_text
from app.services.artifact_service import ArtifactService
from app.services.doc_service import DocService


class IngestionPipeline:
    def __init__(self, db: Session, strategy: str = "v2") -> None:
        self.db = db
        self.cleaner = TextCleaner()
        self.extractor = MetadataExtractor()
        self.embedder = SimpleEmbedder(allow_fallback=False)
        self.doc_service = DocService(db)
        self.artifact_service = ArtifactService(db)
        if strategy != "v2":
            raise ValueError(f"unsupported ingestion strategy: {strategy}")
        self.strategy = strategy
        self.parser = DocumentParser()
        self.chunker = FinancialReportChunkerV2()

    def run(self, file_path: str, overwrite: bool = True) -> dict:
        parsed = self.parser.parse(file_path)
        parsed.elements = self._clean_elements(parsed.elements)
        parsed.text = "\n\n".join(
            element.content for element in parsed.elements if element.element_type == "text"
        )
        metadata = self.extractor.extract(parsed)
        chunks = self.chunker.split_elements(parsed.elements)

        embedding_inputs = [
            self._build_embedding_source(chunk, parsed.title, metadata) for chunk in chunks
        ]
        embeddings = self.embedder.embed_texts(embedding_inputs)
        chunk_records = []
        for chunk, embedding, embedding_source in zip(chunks, embeddings, embedding_inputs):
            chunk_records.append(
                {
                    "chunk_index": chunk.chunk_index,
                    "chunk_type": chunk.chunk_type,
                    "section_title": chunk.section_title,
                    "content": chunk.content,
                    "token_count": chunk.token_count,
                    "page_number": chunk.page_number,
                    "table_title": chunk.table_title,
                    "figure_title": chunk.figure_title,
                    "tokenized_text": " ".join(lexical_tokenize(embedding_source)),
                    "embedding": embedding,
                }
            )

        document, replaced_count = self.doc_service.create_document(
            parsed,
            metadata,
            chunk_records,
            overwrite=overwrite,
        )
        artifacts = self.artifact_service.generate_and_persist(document)
        return {
            "document_id": document.id,
            "title": document.title,
            "chunk_count": len(document.chunks),
            "replaced_count": replaced_count,
            "strategy": self.strategy,
            "artifacts": artifacts,
        }

    def _clean_elements(self, elements: list[ParsedElement]) -> list[ParsedElement]:
        cleaned: list[ParsedElement] = []
        for element in elements:
            content = self.cleaner.clean(element.content)
            if not content:
                continue
            cleaned.append(
                ParsedElement(
                    element_type=element.element_type,
                    content=content,
                    page_number=element.page_number,
                    section_title=element.section_title,
                    table_title=element.table_title,
                    figure_title=element.figure_title,
                )
            )
        return cleaned

    def _build_embedding_source(self, chunk, document_title: str, metadata: dict) -> str:
        return build_embedding_text(
            content=chunk.content,
            document_title=document_title,
            company=metadata.get("company"),
            ticker=metadata.get("ticker"),
            section_title=chunk.section_title,
            table_title=chunk.table_title,
            figure_title=chunk.figure_title,
        )
