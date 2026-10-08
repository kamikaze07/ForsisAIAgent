"""
Component 4: Playbook Loader
Loads all Operational Playbooks from operational-playbooks/.
Exposes execution procedures (prerequisites, execution, verification, rollback, failures).
Execution procedures are derived strictly from Playbooks without inventing steps.
"""

import os
from typing import Dict, List, Optional
from app.runtime.models import PlaybookModel


class PlaybookLoader:
    def __init__(self, playbooks_dir: str = "/home/servidor/forsis-agent/operational-playbooks"):
        self.playbooks_dir = playbooks_dir
        self._playbooks_by_id: Dict[str, PlaybookModel] = {}
        self._playbooks_by_slug: Dict[str, PlaybookModel] = {}

    def load_all(self) -> Dict[str, PlaybookModel]:
        """Load all playbooks from disk."""
        self._playbooks_by_id.clear()
        self._playbooks_by_slug.clear()

        if not os.path.exists(self.playbooks_dir):
            raise FileNotFoundError(f"Playbooks directory not found at: {self.playbooks_dir}")

        for fname in os.listdir(self.playbooks_dir):
            folder = os.path.join(self.playbooks_dir, fname)
            if os.path.isdir(folder) and not fname.startswith("_") and not fname.startswith("."):
                pb = self._load_playbook_folder(fname, folder)
                if pb:
                    self._playbooks_by_id[pb.playbook_id] = pb
                    self._playbooks_by_slug[pb.slug] = pb

        return self._playbooks_by_id

    def _load_playbook_folder(self, slug: str, folder_path: str) -> Optional[PlaybookModel]:
        overview_path = os.path.join(folder_path, "overview.md")
        if not os.path.exists(overview_path):
            return None

        overview_content = self._read_file(overview_path)
        prereqs_content = self._read_file(os.path.join(folder_path, "prerequisites.md"))
        exec_content = self._read_file(os.path.join(folder_path, "execution.md"))
        verif_content = self._read_file(os.path.join(folder_path, "verification.md"))
        rollback_content = self._read_file(os.path.join(folder_path, "rollback.md"))
        failures_content = self._read_file(os.path.join(folder_path, "failures.md"))
        refs_content = self._read_file(os.path.join(folder_path, "references.md"))

        pb_id = f"pb-{slug}"
        title = slug.replace("-", " ").title()
        domain = "General"

        return PlaybookModel(
            playbook_id=pb_id,
            slug=slug,
            title=title,
            domain=domain,
            path=os.path.join("operational-playbooks", slug),
            overview_content=overview_content,
            prerequisites_content=prereqs_content,
            execution_content=exec_content,
            verification_content=verif_content,
            rollback_content=rollback_content,
            failures_content=failures_content,
            references_content=refs_content
        )

    def _read_file(self, filepath: str) -> str:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def get_by_id(self, playbook_id: str) -> Optional[PlaybookModel]:
        return self._playbooks_by_id.get(playbook_id)

    def get_by_slug(self, slug: str) -> Optional[PlaybookModel]:
        return self._playbooks_by_slug.get(slug)

    def list_all(self) -> List[PlaybookModel]:
        return list(self._playbooks_by_id.values())
