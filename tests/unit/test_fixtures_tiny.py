from __future__ import annotations

from tests.fixtures.tiny import chunk_document, tiny_documents


def test_tiny_chunks_are_exact_page_slices() -> None:
    for doc in tiny_documents():
        for chunk in chunk_document(doc):
            page = doc.pages[chunk.page - 1]
            assert page[chunk.char_start : chunk.char_end] == chunk.text


def test_every_tiny_document_is_labelled_synthetic() -> None:
    for doc in tiny_documents():
        assert doc.meta.synthetic
        assert "SYNTHETIC DOCUMENT" in doc.pages[0]
