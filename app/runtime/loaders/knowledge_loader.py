"""
Component 3: Knowledge Loader
Loads and indexes the Operational Knowledge Base (OKB) from operational-knowledge/.
Provides semantic and keyword lookups ("What is this?") based on authoritative OKB docs.
"""

import os
import re
from typing import Dict, List, Optional
from app.runtime.models import KnowledgeModel


class KnowledgeLoader:
    def __init__(self, knowledge_dir: str = "/home/servidor/forsis-agent/operational-knowledge"):
        self.knowledge_dir = knowledge_dir
        self._docs_by_id: Dict[str, KnowledgeModel] = {}
        self._docs_by_path: Dict[str, KnowledgeModel] = {}
        self._keyword_index: Dict[str, List[KnowledgeModel]] = {}

    def load_all(self) -> Dict[str, KnowledgeModel]:
        """Load and index all OKB documents."""
        self._docs_by_id.clear()
        self._docs_by_path.clear()
        self._keyword_index.clear()

        if not os.path.exists(self.knowledge_dir):
            raise FileNotFoundError(f"Knowledge directory not found at: {self.knowledge_dir}")

        for root, _, files in os.walk(self.knowledge_dir):
            for file in files:
                if file.endswith(".md") and not file.startswith("_") and file not in ["README.md", "PREAMBLE.md", "UPDATE_PROCESS.md", "CHANGELOG.md"]:
                    abspath = os.path.join(root, file)
                    relpath = os.path.relpath(abspath, self.knowledge_dir)
                    doc = self._load_doc(file, relpath, abspath)
                    if doc:
                        self._docs_by_id[doc.doc_id] = doc
                        self._docs_by_path[relpath] = doc
                        self._index_doc(doc)

        return self._docs_by_id

    def _load_doc(self, filename: str, relpath: str, abspath: str) -> Optional[KnowledgeModel]:
        with open(abspath, "r", encoding="utf-8") as f:
            content = f.read()

        doc_id = filename.replace(".md", "")
        category = relpath.split(os.sep)[0] if os.sep in relpath else "general"

        # Parse title from first heading
        title = doc_id.replace("-", " ").title()
        title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if title_match:
            title = title_match.group(1).strip()

        # Parse frontmatter status/confidence if present
        status = "validated"
        confidence = "alta"
        summary = content[:200].strip()

        return KnowledgeModel(
            doc_id=doc_id,
            title=title,
            category=category,
            path=os.path.join("operational-knowledge", relpath),
            status=status,
            confidence=confidence,
            summary=summary,
            content=content
        )

    def _index_doc(self, doc: KnowledgeModel) -> None:
        # Extract keywords from title and content
        words = re.findall(r"\w{3,}", doc.title.lower() + " " + doc.content.lower()[:500])
        for w in set(words):
            self._keyword_index.setdefault(w, []).append(doc)

    def search_what_is(self, term: str) -> Optional[KnowledgeModel]:
        """Answer 'What is this?' deterministically from OKB."""
        term_clean = term.lower().strip()

        # Direct match by doc_id
        for doc_id, doc in self._docs_by_id.items():
            if term_clean in doc_id.lower() or doc_id.lower() in term_clean:
                return doc

        # Match by title
        for doc in self._docs_by_id.values():
            if term_clean in doc.title.lower():
                return doc

        # Match by keyword index direct
        matches = self._keyword_index.get(term_clean, [])
        if matches:
            return matches[0]

        # Word fallback search
        words = re.findall(r"\w{3,}", term_clean)
        for w in words:
            if w in self._keyword_index:
                return self._keyword_index[w][0]

        return None

    def get_by_id(self, doc_id: str) -> Optional[KnowledgeModel]:
        return self._docs_by_id.get(doc_id)

    def list_all(self) -> List[KnowledgeModel]:
        return list(self._docs_by_id.values())
