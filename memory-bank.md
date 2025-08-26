## Media Gallery Plugin — Memory Bank

### What it is
- **Purpose**: MkDocs plugin that renders image and YouTube galleries using simple Markdown shortcodes and optional auto-generated category pages.
- **Distribution name**: `mkdocs-media-gallery-plugin`
- **Entry**: `mkdocs_media_gallery/plugin.py` with `MediaGalleryPlugin`.

### How to use
- **Install**:
```bash
pip install mkdocs-media-gallery-plugin
```
- **Configure (`mkdocs.yml`)**:
```yaml
plugins:
  - search
  - media-gallery:
      images_path: images              # relative to docs_dir
      youtube_links_path: youtube-links.yaml  # relative to docs_dir
      generate_category_pages: true    # auto-generate one page per category
```
- **Shortcodes in Markdown**:
  - `{{ gallery_preview }}`: Preview tiles for each image category (one tile per subfolder under `images_path`).
  - `{{ gallery_full category="cats" }}`: Full image gallery for a specific category (folder name).
  - `{{ youtube_gallery }}` or `{{ youtube_gallery category="music" }}`: Renders YouTube videos from YAML, optionally filtered by category.

### Content sources
- **Images**: Folders under `docs/<images_path>/`, one folder per category. Supported extensions: `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`.
  - Category preview image: `thumbnail.jpg` if present, otherwise the first image found.
- **YouTube**: `docs/<youtube_links_path>` YAML file. Two supported shapes:
  - Flat list: list of video IDs or URLs → treated as a single pseudo-category `__flat__`.
  - Categorized dict: `{ category: [ids|urls], ... }`.
  - Video IDs are extracted from common URL formats (`watch?v=`, `youtu.be/`, `/shorts/`, `/live/`, `/embed/`). If a value is already an ID, it is used as-is.

### What gets generated
- If `generate_category_pages: true`:
  - For each image category, a page is created at `docs/galleries/<category>.md` that embeds a full gallery for that category via the `gallery_category_page.html` template.
  - These pages are added to MkDocs' `files` collection so they are part of the build (navigation remains user-defined in `mkdocs.yml`).
- Static assets are copied to the built site under `site/assets/material-galleries/`:
  - `gallery.css`, `gallery.js` (linked by the templates with a relative `base_url`).

### Rendering flow (high level)
1. **on_config**: Initializes a Jinja2 environment loading templates from `mkdocs_media_gallery/templates/`.
2. **on_files**: If enabled, scans image categories and writes Markdown pages into `docs/galleries/` for each category, then appends them to `files` so MkDocs builds them.
3. **on_page_markdown**: Replaces shortcodes in page markdown with rendered HTML:
   - `gallery_preview` → `gallery_preview.html` with all categories.
   - `gallery_full category="..."` → `gallery_full.html` for that category.
   - `youtube_gallery [category="..."]` → `youtube_gallery.html` using parsed YAML.
   Base URL is computed from `page.url` to make assets and links work at any depth.
4. **on_post_build**: Copies CSS/JS into the site output directory.

### Base URL handling
- The plugin computes a `base_url` based on the current page URL to reference assets (`assets/material-galleries/...`) and internal links (`galleries/<category>/`). It uses directory-URL semantics and prepends `../` per path depth.

### Templates and styling
- `templates/gallery_preview.html`: Grid of category tiles with a header and optional "View All" link (to generated category page when enabled).
- `templates/gallery_full.html`: Grid of images for a single category.
- `templates/gallery_category_page.html`: Wrapper used for auto-generated category pages.
- `templates/youtube_gallery.html`: Grid of YouTube thumbnails; when a category is specified or data is flat, renders a list with play overlay.
- `assets/gallery.css`: Dark-themed styles, responsive grid, skeleton loader for image lazy-load, lightbox-friendly classes.
- `assets/gallery.js`: Minimal; lightbox is handled by `mkdocs-glightbox` if present. Templates add `glightbox`-friendly classes (`glightbox`, `data-gallery`, `data-type=video`).

### Important internals (for maintenance)
- Shortcode regexes:
  - `SHORTCODE_PREVIEW = "{{\s*gallery_preview\s*}}"`
  - `SHORTCODE_FULL = "{{\s*gallery_full(?:\s+category=\"(?P<category>[^\"]+)\")?\s*}}"`
  - `SHORTCODE_YOUTUBE = "{{\s*youtube_gallery(?:\s+category=\"(?P<category>[^\"]+)\")?\s*}}"`
- Image scanning (`_scan_galleries`): builds a `Dict[str, GalleryCategory]` where key is the folder name; `preview` prefers `thumbnail.jpg` if present.
- YouTube parsing (`_read_youtube_yaml`): returns `(map, by_category: bool)` where `map` is category→list or `{"__flat__": list}`.
- Base URL (`_calc_base_url_from_url`): computes `../` repetition from `page.url` depth to safely reference assets and links.

### Gotchas and behaviors
- If `gallery_full` is used without a `category`, it renders empty output.
- If `youtube_links_path` is missing or empty, the YouTube gallery renders nothing.
- Generated category pages are Markdown files that inline the rendered HTML; they are recreated on each build in `docs/galleries/`.

### Key files
- `mkdocs_media_gallery/plugin.py`: core plugin, hooks, scanning and rendering.
- `mkdocs_media_gallery/templates/*.html`: Jinja templates for galleries.
- `mkdocs_media_gallery/assets/gallery.css` and `gallery.js`: styling and minimal behavior.
- Example config and docs under `docs/` (`galleries.md`, `youtube-links.yaml`).


### Recent updates
- Optimized writes and copies:
  - Category pages are only rewritten when content changes (`_write_text_if_changed`).
  - Static assets are only copied when bytes differ (`_copy_file_if_changed`).
- Generated category pages now include an H1 heading (`# <category>`) above the embedded gallery.
- Improved logging:
  - Pages log which shortcodes are used and any categories detected.
  - YouTube YAML loader logs counts per category and warns on non-string values (coerced to strings) or invalid shapes.
- YouTube template tweaks (`templates/youtube_gallery.html`):
  - Adds per-category `<h2 id="yt-<name>">` anchors when rendering by category.
  - Uses `glightbox`-friendly markup with `data-type="video"`/`data-source="youtube"`, an overlay play icon, and a skeleton loader.
  - Includes gallery assets via `{{ base_url }}assets/material-galleries/...` and defers JS.
- Packaging/config:
  - Entry point remains `media-gallery = mkdocs_media_gallery.plugin:MediaGalleryPlugin`.
  - Current project version: `1.0.0.dev35` (see `pyproject.toml`).

