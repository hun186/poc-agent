from io import BytesIO
from pathlib import Path
import zipfile, pytest
from requirement_scheduler.artifacts import ArtifactPublisher, output_root_fingerprint

def docx():
    out=BytesIO()
    with zipfile.ZipFile(out,"w") as z:
        z.writestr("[Content_Types].xml","<Types/>"); z.writestr("word/document.xml","<doc/>")
    return out.getvalue()

def test_atomic_publication_and_identical_reconciliation(tmp_path: Path):
    publisher=ArtifactPublisher(tmp_path); fp=output_root_fingerprint(tmp_path)
    first=publisher.publish_or_reconcile("item","report.docx",docx(),fp)
    assert first==publisher.publish_or_reconcile("item","report.docx",docx(),fp)
    assert not Path(first.relative_path).is_absolute()

def test_root_and_docx_fail_closed(tmp_path: Path):
    publisher=ArtifactPublisher(tmp_path)
    with pytest.raises(Exception,match="fingerprint"): publisher.publish_or_reconcile("item","a.docx",docx(),"0"*64)
    with pytest.raises(Exception,match="artifact_invalid"): publisher.publish_or_reconcile("item","a.docx",b"bad",output_root_fingerprint(tmp_path))
