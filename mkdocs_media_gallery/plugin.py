from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import yaml
from mkdocs.config import config_options
from mkdocs.plugins import BasePlugin
from mkdocs.structure.files import Files, File
from mkdocs.structure.pages import Page
from mkdocs.utils import copy_file
from jinja2 import Environment, FileSystemLoader, select_autoescape


SHORTCODE_PREVIEW = r"\{\{\s*gallery_preview\s*\}\}"
SHORTCODE_FULL = r"\{\{\s*gallery_full(?:\s+category=\"(?P<category>[^\"]+)\")?\s*\}\}"
SHORTCODE_YOUTUBE = r"\{\{\s*youtube_gallery(?:\s+category=\"(?P<category>[^\"]+)\")?\s*\}\}"


@dataclass
class GalleryCategory:
    name: str
    images: List[str]
    preview: Optional[str]


class MediaGalleryPlugin(BasePlugin):
    config_scheme = (
        ("images_path", config_options.Type(str, required=True)),
        ("youtube_links_path", config_options.Type(str, default="youtube-links.yaml")),
        ("generate_category_pages", config_options.Type(bool, default=True)),
    )

    env: Environment

    def on_config(self, config, **kwargs):
        templates_dir = Path(__file__).with_name("templates")
        self.env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(["html", "xml"]),
            enable_async=False,
        )
        return config

    def on_files(self, files: Files, config, **kwargs):
        # Generate category pages early so MkDocs can create Page objects for them
        if self.config.get("generate_category_pages", True):
            cats = self._scan_galleries(config["docs_dir"], self.config["images_path"])
            out_dir = Path(config["docs_dir"]) / "galleries"
            out_dir.mkdir(parents=True, exist_ok=True)
            template = self.env.get_template("gallery_category_page.html")
            for cat_name in sorted(cats.keys()):
                # Compute base_url for a page that will be at "galleries/<cat_name>/"
                page_url = f"galleries/{cat_name}/"
                base_url = self._calc_base_url_from_url(page_url)
                html = template.render(category=cats[cat_name], base_url=base_url)
                content = f"""# {cat_name}\n\n{html}\n"""
                md_path = out_dir / f"{cat_name}.md"
                md_path.write_text(content, encoding="utf-8")
                rel = os.path.relpath(md_path, config["docs_dir"]).replace(os.sep, "/")
                if not files.get_file_from_path(rel):
                    files.append(File(rel, config["docs_dir"], config["site_dir"], use_directory_urls=True))
        return files

    def on_post_build(self, config, **kwargs):
        # Copy static assets
        src_assets = Path(__file__).with_name("assets")
        dst_assets = Path(config["site_dir"]) / "assets" / "material-galleries"
        if dst_assets.exists():
            shutil.rmtree(dst_assets)
        dst_assets.mkdir(parents=True, exist_ok=True)
        for name in ["gallery.css", "gallery.js"]:
            copy_file(str(src_assets / name), str(dst_assets / name))

    # ---------- Scanning helpers ----------
    def _scan_galleries(self, docs_dir: str, images_root: str) -> Dict[str, GalleryCategory]:
        root = Path(docs_dir) / images_root
        categories: Dict[str, GalleryCategory] = {}
        if not root.exists():
            return categories
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            category_name = entry.name
            images: List[str] = []
            preview: Optional[str] = None
            thumb = entry / "thumbnail.jpg"
            for img in sorted(entry.iterdir()):
                if img.is_file() and img.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
                    rel = f"{images_root}/{category_name}/{img.name}"
                    images.append(rel)
            if images:
                if thumb.exists():
                    preview = f"{images_root}/{category_name}/thumbnail.jpg"
                else:
                    preview = images[0]
            categories[category_name] = GalleryCategory(name=category_name, images=images, preview=preview)
        return categories

    def _read_youtube_yaml(self, docs_dir: str, path: str) -> Tuple[Dict[str, List[str]], bool]:
        yaml_path = Path(docs_dir) / path
        if not yaml_path.exists():
            return ({}, False)
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        if not data:
            return ({}, False)
        # If list -> flat category "__flat__"
        if isinstance(data, list):
            return ({"__flat__": [self._extract_yt_id(x) for x in data]}, False)
        # Dict of categories
        result: Dict[str, List[str]] = {}
        for cat, items in data.items():
            if isinstance(items, list):
                result[cat] = [self._extract_yt_id(x) for x in items]
        return (result, True)

    def _extract_yt_id(self, value: str) -> str:
        v = value.strip()
        if "youtube.com" in v or "youtu.be" in v:
            # shorts, live, embed, watch and youtu.be formats
            for pattern in [
                r"v=([\w-]{6,})",
                r"youtu\.be/([\w-]{6,})",
                r"youtube\.com/(?:shorts|live)/([\w-]{6,})",
                r"youtube\.com/embed/([\w-]{6,})",
            ]:
                m = re.search(pattern, v)
                if m:
                    return m.group(1)
        return v

    def _calc_base_url_from_url(self, page_url: str) -> str:
        if not page_url:
            return ""
        # ensure trailing slash for directory-urls semantics
        path = page_url if page_url.endswith('/') else (page_url.rsplit('/', 1)[0] + '/')
        segments = [s for s in path.split('/') if s]
        depth = len(segments)
        return "../" * depth

    # ---------- Rendering ----------
    def _render_preview(self, categories: Dict[str, GalleryCategory], base_url: str) -> str:
        template = self.env.get_template("gallery_preview.html")
        return template.render(
            categories=categories,
            base_url=base_url,
            generate_category_pages=self.config.get("generate_category_pages", True),
        )

    def _render_full(self, categories: Dict[str, GalleryCategory], category: str, base_url: str) -> str:
        template = self.env.get_template("gallery_full.html")
        cat = categories.get(category)
        return template.render(category=cat, base_url=base_url)

    def _render_youtube(self, yt_map: Dict[str, List[str]], by_category: bool, category: Optional[str], base_url: str) -> str:
        template = self.env.get_template("youtube_gallery.html")
        if category:
            vids = yt_map.get(category) or yt_map.get("__flat__", [])
            return template.render(by_category=False, single_category=category, videos=vids, base_url=base_url)
        if by_category:
            return template.render(by_category=True, categories=yt_map, base_url=base_url)
        # flat list
        vids = yt_map.get("__flat__", [])
        return template.render(by_category=False, single_category=None, videos=vids, base_url=base_url)

    # ---------- Page hooks ----------
    def on_page_markdown(self, markdown: str, page: Page, config, files: Files):
        cats = self._scan_galleries(config["docs_dir"], self.config["images_path"])
        yt_map, by_cat = self._read_youtube_yaml(config["docs_dir"], self.config.get("youtube_links_path", "youtube-links.yaml"))
        base_url = self._calc_base_url_from_url(page.url)

        def replace_preview(match):
            return self._render_preview(cats, base_url)

        def replace_full(match):
            cat = match.group("category")
            if not cat:
                return ""
            return self._render_full(cats, cat, base_url)

        def replace_youtube(match):
            cat = match.group("category")
            return self._render_youtube(yt_map, by_cat, cat, base_url)

        markdown = re.sub(SHORTCODE_PREVIEW, replace_preview, markdown)
        markdown = re.sub(SHORTCODE_FULL, replace_full, markdown)
        markdown = re.sub(SHORTCODE_YOUTUBE, replace_youtube, markdown)
        return markdown

    def on_nav(self, nav, config, files: Files):
        # No file appends here; category pages are generated in on_files
        return nav
