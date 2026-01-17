"""Guide API endpoints.

Provides endpoints for loading and searching tutorial content.
"""

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query

from frago.server.services.guide_service import GuideService

router = APIRouter()


@router.get("/guide/meta")
async def get_guide_meta(lang: str = Query("en", description="Language code")) -> Dict[str, Any]:
    """Get guide metadata.

    Returns guide structure, categories, and available chapters.

    Args:
        lang: Language code (not used in meta, but kept for consistency)

    Returns:
        Guide metadata dictionary

    Raises:
        HTTPException: 404 if metadata not found, 500 on other errors
    """
    try:
        meta = GuideService.load_meta()
        return meta
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=f"Guide metadata not found: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load guide metadata: {str(e)}"
        )


@router.get("/guide/content")
async def get_guide_content(
    lang: str = Query(..., description="Language code (e.g., 'en', 'zh-CN')"),
    chapter: str = Query(..., description="Chapter ID"),
) -> Dict[str, Any]:
    """Get chapter content.

    Returns full chapter content with metadata and table of contents.

    Args:
        lang: Language code (required)
        chapter: Chapter ID (required)

    Returns:
        Chapter content dictionary with:
            - id: Chapter ID
            - title: Chapter title
            - category: Category ID
            - content: Markdown content
            - metadata: Version, tags, etc.
            - toc: Table of contents

    Raises:
        HTTPException: 400 for invalid params, 404 if not found, 500 on errors
    """
    try:
        content = GuideService.load_chapter(lang, chapter)
        return content
    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail=f"Chapter not found: {str(e)}"
        )
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=f"Chapter file not found: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load chapter content: {str(e)}"
        )


@router.get("/guide/search")
async def search_guide(
    q: str = Query(..., description="Search query", min_length=1),
    lang: str = Query("en", description="Language code"),
) -> Dict[str, Any]:
    """Search guide content.

    Searches through all chapters for the given query and returns matching sections.

    Args:
        q: Search query (required, minimum 1 character)
        lang: Language code (default: 'en')

    Returns:
        Search results dictionary with:
            - query: Original search query
            - total: Total number of matches
            - results: List of matching chapters and sections

    Raises:
        HTTPException: 400 for invalid query, 500 on errors
    """
    try:
        results = GuideService.search_content(q, lang)

        return {
            "query": q,
            "total": sum(len(r["matches"]) for r in results),
            "results": results,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Search failed: {str(e)}"
        )
