# tests/test_doc_processor_guardrails.py
import ast
import pytest

def test_imports_use_correct_docling_and_no_banned_fallbacks():
    """Verify code uses official Docling imports and strictly bans PyPDF2/pypdf fallbacks."""
    with open("ingestion/doc_processor.py", "r") as f:
        source_code = f.read()

    tree = ast.parse(source_code)
    
    imported_modules = []
    imported_from_modules = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_from_modules.append(node.module)

    # 1. Ensure PyPDF2 or pypdf are never imported
    banned_libraries = ["PyPDF2", "pypdf", "fitz", "pdfplumber"]
    for banned in banned_libraries:
        assert banned not in imported_modules, f"Banned fallback library '{banned}' detected in imports!"
        assert banned not in imported_from_modules, f"Banned fallback library '{banned}' detected in from-imports!"

    # 2. Enforce official Docling DocumentConverter import path
    assert "docling.document_converter" in imported_from_modules, (
        "Docling must be imported from 'docling.document_converter', not hallucinated top-level modules!"
    )