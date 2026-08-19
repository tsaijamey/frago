"""A page's data channel must never let a failure stick to a device.

Reported from the field: the same account, the same page, opened on a phone and
on a computer. The phone showed the ledger. The computer showed nothing. Nothing
was wrong on the server by the time anyone looked — the account's slot, its
directory and its files were all in place.

The computer had opened the page once *before* that data existed, got a 404, and
kept it. A 404 is heuristically cacheable, so with no cache directive on it the
browser is entitled to answer the next request itself, indefinitely. The person
sees a page that stays broken after the thing that broke it has been fixed, and
no amount of looking at the server explains it.

So every failure on this route carries `no-store`. Success may be revalidated;
failure is never remembered.
"""

import inspect

from frago.server.routes import app_pages


def test_no_store_is_declared():
    assert app_pages._NO_STORE == {"Cache-Control": "no-store"}


def test_every_failure_on_the_data_route_is_uncacheable():
    """Any 404 raised while serving a page's data must say not to keep it."""
    source = inspect.getsource(app_pages.serve_app_data)

    raises = [line for line in source.splitlines() if "HTTPException" in line]
    assert raises, "the data route no longer raises; this test needs rewriting"

    # Each raise either carries the header inline or opens a call that does.
    blocks = source.split("raise HTTPException")[1:]
    missing = [b.split(")")[0] for b in blocks if "_NO_STORE" not in b.split("raise ")[0]]
    assert not missing, f"these failures could be cached by the browser: {missing}"


def test_success_still_revalidates_rather_than_never_caching():
    """Data files are big and change rarely; forbidding cache entirely is waste.

    Revalidation is the right setting for them — the browser asks, the server
    answers 304 when nothing moved. Only the failures need to be forgotten.
    """
    source = inspect.getsource(app_pages.serve_app_data)

    assert "_REVALIDATE" in source
