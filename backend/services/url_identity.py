"""URL -> gallery identity, for routers that must not import plugin internals."""


def account_gallery_key(url: str) -> tuple[str, str] | None:
    """``(source, source_id)`` of the account gallery ``url`` points at.

    Only account URLs name a gallery on their own (the gallery *is* the
    account). A work, search or tag URL has no stable gallery of its own, and
    an unparseable URL has none at all; both return ``None``. Mirrors the key
    the importer upserts on, so ``weibo.cn`` and ``weibo.com`` spellings of the
    same account resolve to the same gallery.
    """
    from plugins.builtin.gallery_dl._identity import resolve_url_identity

    try:
        identity = resolve_url_identity(url)
    except Exception:
        return None
    if identity is None or not identity.is_account:
        return None
    return identity.source, identity.source_id
