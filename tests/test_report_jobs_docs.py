from pathlib import Path
import xml.etree.ElementTree as ET
def test_job_documentation_and_svgs_exist():
    for name in ["docs/architecture/dual-mode-report-api.md","docs/api/report-api.md","docs/operations/report-jobs.md"]: assert Path(name).is_file()
    for name in ["docs/architecture/dual-mode-report-api.svg","docs/architecture/report-job-lifecycle.svg"]: ET.parse(name)
