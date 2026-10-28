"""
storage.py
==========
Where captured viewer snapshots and their JSON go. Today everything is written
to a folder; to move to S3 / GCS / Azure, add a class with the same `save`
method and return it from `get_storage` - the rest of the pipeline only deals
in keys such as "captures/person_3.jpg".
"""

from pathlib import Path


class LocalStorage:
    """Writes files under a root folder (one per job)."""

    def __init__(self, root):
        self.root = Path(root).resolve()

    def save(self, key: str, data: bytes) -> str:
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError(f"Storage key escapes the root folder: {key}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return Path(key).as_posix()


def get_storage(job_dir):
    return LocalStorage(job_dir)
