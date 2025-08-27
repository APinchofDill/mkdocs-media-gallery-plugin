# MKDOCS Media Galleries 

MkDocs plugin for that adds image and YouTube galleries with shortcodes.

## Install

```bash
pip install mkdocs-media-gallery-plugin
```

## Configure (mkdocs.yml)

```yaml
plugins:
  - search
  - media-gallery:
      images_path: images            # relative to docs_dir
      youtube_links_path: youtube-links.yaml  # relative to docs_dir
      generate_category_pages: true  # auto-generate one page per category
```

## Shortcodes in Markdown

- `{{ gallery_preview }}`: Shows preview tiles for each category (folder under images_path)
- `{{ gallery_full category="cats" }}`: Shows full gallery for the given category
- `{{ youtube_gallery }}`: Renders YouTube gallery from YAML (optionally `category="..."`)

## YouTube data (docs/youtube-links.yaml)

```yaml
# Either flat list
- https://www.youtube.com/watch?v=ZucM9aw6Qlo
- sHfe3nT5-jk

# Or categorized
Music:
- https://www.youtube.com/watch?v=mEK0owuRoks
Shows:
- https://www.youtube.com/watch?v=ZucM9aw6Qlo
```
