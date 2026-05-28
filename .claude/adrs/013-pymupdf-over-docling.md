# ADR 013: Replace Docling with PyMuPDF for RAG PDF parsing

- Status: Accepted
- Date: 2026-05-28

## Context

The RAG ingest pipeline parses six TfL strategy PDFs into chunks before
embedding them with Bedrock Titan and upserting to pgvector. Parsing used
Docling, whose `DocumentConverter` loads torch-based layout models.

Two problems make Docling the wrong tool here:

- **Resource cost.** Docling pulls torch + transformers transitively
  (~multi-GB of wheels) and the layout parse needs several GB of RAM,
  taking ~8 minutes per PDF on CPU. It cannot run on the shared 2 GB
  Lightsail box without OOMing every tenant, so the ingest is forced
  off-box, and even off-box it burns the author's workstation RAM for the
  duration. The torch payload also bloated the production image enough to
  need a CPU-only wheel pin.
- **No payoff for this corpus.** The TfL documents are born-digital prose
  exports. Docling's value-add — layout reconstruction, table structure,
  OCR — adds nothing over plain text extraction for these files. OCR was
  already disabled (`do_ocr=False`).

The warehouse-recreation cycle behind TM-31 (a fresh Supabase project each
time the free tier fills) means the RAG vectors must be re-ingested on every
recreation. A 45-minute, RAM-saturating, off-box-only parse on each cycle is
untenable.

PDF parsing is listed as a "locked" stack choice in CLAUDE.md, so swapping it
warrants an ADR.

## Decision

Replace Docling with **PyMuPDF** for text extraction and **LlamaIndex's
`SentenceSplitter`** for chunking. LlamaIndex remains the RAG framework
(embeddings, vector store, retrieval) — only the PDF→text→chunks stages
change.

- Drop `docling>=2.0` from the `rag` dependency group; add `pymupdf>=1.24`.
- `src/rag/parse.py`: `_PyMuPdfExtractor` emits one `PageText` per page;
  each page's text is split by `SentenceSplitter` (512-token chunks, 64
  overlap). Both stages stay behind injectable Protocols
  (`_PdfExtractor`, `_TextSplitter`) so unit tests inject lightweight fakes.
- Remove the CPU-only torch index pin (`[[tool.uv.index]] pytorch-cpu` and
  the `tool.uv.sources` torch entries): torch and transformers were
  Docling-only transitive dependencies and are now orphaned.
- Update the mypy overrides (drop `docling`, add `pymupdf`).

## Consequences

- RAG ingest runs on the workstation in seconds with no torch, no OOM risk,
  and no off-box requirement. Re-ingesting a recreated project is cheap.
- The production image drops torch/triton/nvidia wheels (~multi-GB lighter),
  easing the image-unpack disk pressure seen on the Lightsail box.
- Chunk granularity changes (per-page, sentence-aware; `section_title` is no
  longer populated since PyMuPDF text mode carries no heading hierarchy).
  Every per-chunk vector id therefore changes, so the next ingest is a full
  rebuild — acceptable, as the warehouse is being recreated regardless.
- Loses Docling's table/heading structure extraction. Acceptable for prose
  strategy documents; revisit with an ADR if a future source needs rich
  table parsing.
- `src/api/Dockerfile` can drop the Docling-only system libraries
  (`libgl1`, `libxcb1`) and the Hugging Face cache directory in a follow-up;
  they are dead weight once torch/Docling are gone.
- The CLAUDE.md tech-stack table lists PyMuPDF instead of Docling for PDF
  ingestion.
