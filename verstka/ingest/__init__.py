"""Ingest: read the PPTX package, render slides to images, manage the template workspace."""

from verstka.ingest.package import PptxPackage, Rel
from verstka.ingest.render import RenderError, render_slides
from verstka.ingest.workspace import TemplateWorkspace, file_sha256

__all__ = ["PptxPackage", "Rel", "RenderError", "render_slides", "TemplateWorkspace", "file_sha256"]
