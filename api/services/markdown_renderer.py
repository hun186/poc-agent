# api/services/markdown_renderer.py
from typing import Any, Optional
from fastapi import Request

from api.core.presenters.extractors import extract_presentation
from api.core.presenters.markdown_presenter import build_markdown


def render_markdown(out: Any, request: Request, session_id: Optional[str] = None) -> str:
    pres = extract_presentation(out)
    return build_markdown(pres, request, session_id=session_id)
