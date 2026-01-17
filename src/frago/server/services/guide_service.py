"""Guide service for loading and serving tutorial content."""

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

try:
    import frontmatter
except ImportError:
    frontmatter = None  # Will handle gracefully


class GuideService:
    """Service for managing guide/tutorial content."""

    @staticmethod
    def get_guide_dir() -> Path:
        """Get guide directory.

        Priority:
        1. User directory: ~/.frago/guide/
        2. Package resources: src/frago/resources/guide/

        Returns:
            Path to guide directory
        """
        # Check user directory first
        user_guide = Path.home() / ".frago" / "guide"
        if user_guide.exists() and (user_guide / "meta.json").exists():
            return user_guide

        # Check package resources
        try:
            from frago.resources import guide as guide_pkg

            pkg_guide = Path(guide_pkg.__file__).parent
            if pkg_guide.exists() and (pkg_guide / "meta.json").exists():
                return pkg_guide
        except (ImportError, AttributeError):
            pass

        # If nothing found, return user directory path (will be created)
        return user_guide

    @staticmethod
    @lru_cache(maxsize=1)
    def load_meta() -> Dict:
        """Load guide metadata.

        Returns:
            Guide metadata dictionary

        Raises:
            FileNotFoundError: If meta.json not found
            json.JSONDecodeError: If meta.json is invalid
        """
        guide_dir = GuideService.get_guide_dir()
        meta_file = guide_dir / "meta.json"

        if not meta_file.exists():
            raise FileNotFoundError(
                f"Guide metadata not found at {meta_file}. "
                "Please reinstall frago or check ~/.frago/guide/ directory."
            )

        return json.loads(meta_file.read_text(encoding="utf-8"))

    @staticmethod
    @lru_cache(maxsize=128)
    def load_chapter(lang: str, chapter_id: str) -> Dict:
        """Load chapter content.

        Args:
            lang: Language code (e.g., 'en', 'zh-CN')
            chapter_id: Chapter identifier

        Returns:
            Chapter content dictionary with:
                - id: Chapter ID
                - title: Chapter title
                - category: Category ID
                - content: Markdown content
                - metadata: Chapter metadata (version, tags, etc.)
                - toc: Table of contents

        Raises:
            ValueError: If chapter not found in meta.json
            FileNotFoundError: If chapter file not found
        """
        meta = GuideService.load_meta()

        # Find chapter configuration
        chapter = next(
            (c for c in meta["chapters"] if c["id"] == chapter_id),
            None,
        )
        if not chapter:
            raise ValueError(f"Chapter '{chapter_id}' not found in meta.json")

        # Get file path
        guide_dir = GuideService.get_guide_dir()
        file_path = guide_dir / chapter["files"][lang]

        if not file_path.exists():
            raise FileNotFoundError(
                f"Chapter file not found: {file_path}\n"
                f"Expected at: {chapter['files'][lang]}"
            )

        # Parse Markdown + frontmatter
        if frontmatter is None:
            # Fallback: manual parsing if python-frontmatter not installed
            content_text = file_path.read_text(encoding="utf-8")
            metadata, content = GuideService._parse_frontmatter_manual(content_text)
        else:
            with open(file_path, "r", encoding="utf-8") as f:
                post = frontmatter.load(f)
                metadata = dict(post.metadata)
                content = post.content

        # Extract table of contents
        toc = GuideService._extract_toc(content)

        return {
            "id": chapter_id,
            "title": metadata.get("title", ""),
            "category": metadata.get("category", ""),
            "content": content,
            "metadata": {
                "version": metadata.get("version", ""),
                "last_updated": metadata.get("last_updated", ""),
                "tags": metadata.get("tags", []),
                "order": metadata.get("order", 0),
            },
            "toc": toc,
        }

    @staticmethod
    def _parse_frontmatter_manual(text: str) -> tuple[Dict, str]:
        """Manually parse YAML frontmatter if python-frontmatter not available.

        Args:
            text: Full markdown text with frontmatter

        Returns:
            Tuple of (metadata dict, content string)
        """
        import yaml

        # Check if starts with ---
        if not text.startswith("---\n"):
            return {}, text

        # Find end of frontmatter
        parts = text.split("\n---\n", 2)
        if len(parts) < 2:
            return {}, text

        # Parse YAML
        try:
            metadata = yaml.safe_load(parts[1])
            content = parts[2] if len(parts) > 2 else ""
            return metadata or {}, content
        except Exception:
            return {}, text

    @staticmethod
    def _extract_toc(content: str) -> List[Dict]:
        """Extract table of contents from Markdown headings.

        Args:
            content: Markdown content

        Returns:
            List of TOC entries with level, title, and anchor
        """
        toc = []
        heading_pattern = r"^(#{2,6})\s+(.+)$"

        for line in content.split("\n"):
            match = re.match(heading_pattern, line)
            if match:
                level = len(match.group(1))
                title = match.group(2).strip()
                anchor = GuideService._slugify(title)
                toc.append({
                    "level": level,
                    "title": title,
                    "anchor": anchor,
                })

        return toc

    @staticmethod
    def _slugify(text: str) -> str:
        """Generate anchor ID from heading text.

        Supports both English and Chinese characters.

        Args:
            text: Heading text

        Returns:
            Slugified anchor ID
        """
        import unicodedata

        # Normalize unicode
        text = unicodedata.normalize("NFKD", text)

        # Remove special characters, keep alphanumeric and Chinese
        text = re.sub(r"[^\w\s\u4e00-\u9fff-]", "", text.lower())

        # Replace whitespace with hyphens
        text = re.sub(r"[\s_]+", "-", text)

        return text.strip("-")

    @staticmethod
    def search_content(query: str, lang: str) -> List[Dict]:
        """Search guide content for keywords.

        Args:
            query: Search query string
            lang: Language code

        Returns:
            List of search results with chapter info and matched snippets
        """
        if not query or not query.strip():
            return []

        meta = GuideService.load_meta()
        results = []
        query_lower = query.lower()

        for chapter in meta["chapters"]:
            try:
                content_data = GuideService.load_chapter(lang, chapter["id"])
                matches = []

                # Search in content by paragraphs
                paragraphs = content_data["content"].split("\n\n")
                for para in paragraphs:
                    if query_lower in para.lower():
                        # Extract question if this is a Q&A section
                        if para.startswith("## Q:"):
                            question = para.split("\n")[0].replace("## Q:", "").strip()
                            snippet = GuideService._highlight_snippet(
                                para, query, max_length=200
                            )
                            anchor = GuideService._slugify(para.split("\n")[0])
                            matches.append({
                                "question": question,
                                "snippet": snippet,
                                "anchor": anchor,
                            })

                if matches:
                    results.append({
                        "chapter_id": chapter["id"],
                        "chapter_title": content_data["title"],
                        "matches": matches,
                    })

            except Exception as e:
                # Log error but continue searching other chapters
                print(f"Error searching chapter {chapter['id']}: {e}")
                continue

        return results

    @staticmethod
    def _highlight_snippet(text: str, query: str, max_length: int = 200) -> str:
        """Extract snippet with highlighted search keyword.

        Args:
            text: Full text
            query: Search query
            max_length: Maximum snippet length

        Returns:
            Snippet with <mark> tags around query
        """
        # Find keyword position
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        match = pattern.search(text)

        if not match:
            return text[:max_length] + ("..." if len(text) > max_length else "")

        # Extract surrounding text
        start = max(0, match.start() - 50)
        end = min(len(text), match.end() + 150)
        snippet = text[start:end]

        # Highlight keyword
        snippet = pattern.sub(f"<mark>{match.group()}</mark>", snippet)

        # Add ellipsis
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(text) else ""

        return prefix + snippet + suffix
