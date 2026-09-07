from __future__ import annotations
from dataclasses import dataclass
import hashlib, io, os
from pathlib import Path
import zipfile

from .execution import ExecutionFailure, FailureCategory

def canonical_root_identity(root: Path) -> str:
    return os.path.normcase(str(root.expanduser().resolve(strict=False)))

def output_root_fingerprint(root: Path) -> str:
    return hashlib.sha256(canonical_root_identity(root).encode("utf-8")).hexdigest()

@dataclass(frozen=True)
class PublishedArtifact:
    relative_path: str
    sha256: str

def _validate_docx(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            names=set(package.namelist())
            if "[Content_Types].xml" not in names or "word/document.xml" not in names: raise ValueError
            if any(name.startswith("/") or ".." in Path(name).parts for name in names): raise ValueError
            package.testzip()
    except (ValueError, zipfile.BadZipFile, OSError) as exc:
        raise ExecutionFailure(FailureCategory.ARTIFACT_INVALID, "artifact_invalid") from exc
    return hashlib.sha256(data).hexdigest()

class ArtifactPublisher:
    def __init__(self, root: Path): self.root=Path(root)
    def publish_or_reconcile(self, run_item_id: str, logical_filename: str, data: bytes, expected_root_fingerprint: str) -> PublishedArtifact:
        if output_root_fingerprint(self.root) != expected_root_fingerprint: raise ExecutionFailure(FailureCategory.INTERNAL_CONTRACT_VIOLATION, "output_root_fingerprint_mismatch")
        digest=_validate_docx(data)
        safe_item="".join(c for c in run_item_id if c.isalnum() or c in "-_")
        safe_name=Path(logical_filename).name
        if safe_name != logical_filename or not safe_name.lower().endswith(".docx") or not safe_item: raise ExecutionFailure(FailureCategory.ARTIFACT_PUBLICATION_FAILED, "artifact_path_invalid")
        relative=Path(safe_item[:64]) / safe_name
        final=(self.root / relative).resolve(strict=False)
        root=self.root.resolve(strict=False)
        if root not in final.parents: raise ExecutionFailure(FailureCategory.ARTIFACT_PUBLICATION_FAILED, "artifact_path_invalid")
        final.parent.mkdir(parents=True, exist_ok=True)
        if final.exists():
            existing=final.read_bytes()
            if _validate_docx(existing) != digest: raise ExecutionFailure(FailureCategory.ARTIFACT_PUBLICATION_FAILED, "artifact_conflict")
            return PublishedArtifact(relative.as_posix(), digest)
        temp=final.with_name(f".{final.name}.{os.getpid()}.tmp")
        try:
            with open(temp,"xb") as stream:
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
            os.link(temp, final)
            os.unlink(temp)
            fd=os.open(final.parent, os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
        except FileExistsError:
            temp.unlink(missing_ok=True)
            if _validate_docx(final.read_bytes()) != digest: raise ExecutionFailure(FailureCategory.ARTIFACT_PUBLICATION_FAILED, "artifact_conflict")
        except OSError as exc:
            temp.unlink(missing_ok=True)
            raise ExecutionFailure(FailureCategory.ARTIFACT_PUBLICATION_FAILED, "artifact_publication_failed") from exc
        return PublishedArtifact(relative.as_posix(),digest)
