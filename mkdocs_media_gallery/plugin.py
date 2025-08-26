from __future__ import annotations

import os
import re
import shutil
import logging
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

# Module-level logger (inherits level/handlers from MkDocs/root logger)
log = logging.getLogger("mkdocs.media_gallery")


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
        log.debug(
            "MediaGalleryPlugin configured: images_path=%s, youtube_links_path=%s, generate_category_pages=%s",
            self.config.get("images_path"),
            self.config.get("youtube_links_path", "youtube-links.yaml"),
            self.config.get("generate_category_pages", True),
        )
        return config

    def on_files(self, files: Files, config, **kwargs):
        # Generate category pages early so MkDocs can create Page objects for them
        if self.config.get("generate_category_pages", True):
            cats = self._scan_galleries(config["docs_dir"], self.config["images_path"])
            out_dir = Path(config["docs_dir"]) / "galleries"
            out_dir.mkdir(parents=True, exist_ok=True)
            template = self.env.get_template("gallery_category_page.html")
            written_changes = 0
            for cat_name in sorted(cats.keys()):
                # Compute base_url for a page that will be at "galleries/<cat_name>/"
                page_url = f"galleries/{cat_name}/"
                base_url = self._calc_base_url_from_url(page_url)
                html = template.render(category=cats[cat_name], base_url=base_url)
                content = f"""# {cat_name}\n\n{html}\n"""
                md_path = out_dir / f"{cat_name}.md"
                if self._write_text_if_changed(md_path, content):
                    written_changes += 1
                rel = os.path.relpath(md_path, config["docs_dir"]).replace(os.sep, "/")
                if not files.get_file_from_path(rel):
                    files.append(File(rel, config["docs_dir"], config["site_dir"], use_directory_urls=True))
            log.info("Checked %d category page(s); wrote %d change(s) in %s", len(cats), written_changes, out_dir)
        return files

    def on_post_build(self, config, **kwargs):
        # Copy static assets only if changed to avoid unnecessary filesystem churn
        src_assets = Path(__file__).with_name("assets")
        dst_assets = Path(config["site_dir"]) / "assets" / "material-galleries"
        dst_assets.mkdir(parents=True, exist_ok=True)
        copied = 0
        for name in ["gallery.css", "gallery.js"]:
            src = src_assets / name
            dst = dst_assets / name
            if self._copy_file_if_changed(src, dst):
                copied += 1
        log.debug("Checked assets; copied %d change(s) into %s", copied, dst_assets)

    # ---------- Scanning helpers ----------
    def _scan_galleries(self, docs_dir: str, images_root: str) -> Dict[str, GalleryCategory]:
        root = Path(docs_dir) / images_root
        categories: Dict[str, GalleryCategory] = {}
        if not root.exists():
            log.warning("Images root not found: %s", root)
            return categories
        log.debug("Scanning image categories under %s", root)
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
            log.debug(
                "Category '%s': %d image(s), preview=%s",
                category_name,
                len(images),
                preview,
            )
        log.info("Scanned %d image category(ies)", len(categories))
        return categories

    def _read_youtube_yaml(self, docs_dir: str, path: str) -> Tuple[Dict[str, List[str]], bool]:
        yaml_path = Path(docs_dir) / path
        if not yaml_path.exists():
            log.warning("YouTube links file not found: %s", yaml_path)
            return ({}, False)
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        except Exception as e:
            log.error("Failed to parse YouTube YAML at %s: %s", yaml_path, e)
            return ({}, False)
        if data is None or data == {} or data == []:
            log.warning("YouTube links file is empty: %s", yaml_path)
            return ({}, False)
        # If list -> flat category "__flat__"
        if isinstance(data, list):
            non_str_count = sum(1 for x in data if not isinstance(x, str))
            if non_str_count:
                log.warning(
                    "YouTube links list contains %d non-string entrie(s); coercing to string",
                    non_str_count,
                )
            vids = [self._extract_yt_id(str(x)) for x in data if x is not None]
            log.info("Loaded %d YouTube video(s) from flat list at %s", len(vids), yaml_path)
            return ({"__flat__": vids}, False)
        # Dict of categories
        if not isinstance(data, dict):
            log.error(
                "YouTube links file has invalid structure at %s: expected list or dict, got %s",
                yaml_path,
                type(data).__name__,
            )
            return ({}, False)
        result: Dict[str, List[str]] = {}
        invalid_value_keys: List[str] = []
        for cat, items in data.items():
            if isinstance(items, list):
                non_str_count = sum(1 for x in items if not isinstance(x, str))
                if non_str_count:
                    log.warning(
                        "YouTube category '%s' contains %d non-string entrie(s); coercing to string",
                        cat,
                        non_str_count,
                    )
                cat_name = str(cat)
                result[cat_name] = [self._extract_yt_id(str(x)) for x in items if x is not None]
                log.debug("YouTube category '%s': %d video(s)", cat_name, len(result[cat_name]))
            else:
                invalid_value_keys.append(str(cat))
        if invalid_value_keys:
            log.warning(
                "YouTube links file has non-list values for categor(ies) %s; those entries were ignored",
                ", ".join(invalid_value_keys),
            )
        log.info("Loaded YouTube links for %d categor(ies) from %s", len(result), yaml_path)
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
    def _write_text_if_changed(self, path: Path, content: str) -> bool:
        """Write text to a file only if the content has actually changed.

        Returns True if the file was written (created or updated), False if unchanged.
        """
        try:
            if path.exists():
                current = path.read_text(encoding="utf-8")
                if current == content:
                    return False
        except Exception:
            # If reading fails for any reason, fall back to writing
            pass
        path.write_text(content, encoding="utf-8")
        return True

    def _copy_file_if_changed(self, src: Path, dst: Path) -> bool:
        """Copy file only when bytes differ. Returns True if copied (created/updated)."""
        try:
            if dst.exists():
                try:
                    src_bytes = src.read_bytes()
                    dst_bytes = dst.read_bytes()
                    if src_bytes == dst_bytes:
                        return False
                except Exception:
                    # If reading fails, fall back to copying
                    pass
            # Ensure parent exists
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
            return True
        except Exception:
            # On any unexpected error, avoid raising to not break the build
            try:
                shutil.copy2(str(src), str(dst))
                return True
            except Exception:
                return False
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
        # Pre-scan for shortcode occurrences to log which pages use them
        preview_matches = re.findall(SHORTCODE_PREVIEW, markdown)
        full_iter = list(re.finditer(SHORTCODE_FULL, markdown))
        yt_iter = list(re.finditer(SHORTCODE_YOUTUBE, markdown))

        full_categories = [m.group("category") for m in full_iter if m.group("category")]
        yt_categories = [m.group("category") for m in yt_iter if m.group("category")]

        page_name = getattr(getattr(page, "file", None), "src_path", None) or page.url
        if preview_matches or full_iter or yt_iter:
            log.info(
                "Shortcodes on page '%s': preview=%d, full=%d%s, youtube=%d%s",
                page_name,
                len(preview_matches),
                len(full_iter),
                (f" (cats={full_categories})" if full_categories else ""),
                len(yt_iter),
                (f" (cats={yt_categories})" if yt_categories else ""),
            )

        # Only scan image categories (and therefore only log about it) if preview/full shortcode(s) are present
        cats: Dict[str, GalleryCategory] = {}
        if preview_matches or full_iter:
            cats = self._scan_galleries(config["docs_dir"], self.config["images_path"])
        # Only read YouTube YAML (and therefore only log about it) if youtube shortcode(s) are present
        yt_map: Dict[str, List[str]] = {}
        by_cat: bool = False
        if yt_iter:
            yt_map, by_cat = self._read_youtube_yaml(
                config["docs_dir"], self.config.get("youtube_links_path", "youtube-links.yaml")
            )
        base_url = self._calc_base_url_from_url(page.url)

        def replace_preview(match):
            log.info("Rendering shortcode 'gallery_preview' on page '%s'", page_name)
            return self._render_preview(cats, base_url)

        def replace_full(match):
            cat = match.group("category")
            if not cat:
                return ""
            log.info("Rendering shortcode 'gallery_full' (category='%s') on page '%s'", cat, page_name)
            return self._render_full(cats, cat, base_url)

        def replace_youtube(match):
            cat = match.group("category")
            if cat:
                log.info("Rendering shortcode 'youtube_gallery' (category='%s') on page '%s'", cat, page_name)
            else:
                log.info(
                    "Rendering shortcode 'youtube_gallery' (%s) on page '%s'",
                    "by-category" if by_cat else "flat",
                    page_name,
                )
            return self._render_youtube(yt_map, by_cat, cat, base_url)

        markdown = re.sub(SHORTCODE_PREVIEW, replace_preview, markdown)
        markdown = re.sub(SHORTCODE_FULL, replace_full, markdown)
        markdown = re.sub(SHORTCODE_YOUTUBE, replace_youtube, markdown)
        return markdown

    def on_nav(self, nav, config, files: Files):
        # No file appends here; category pages are generated in on_files
        return nav
