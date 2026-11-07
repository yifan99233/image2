def canonicalize_asset_url(value: str | None) -> str:
    url = (value or "").strip()
    return url.replace("https://magic.shyfai.com/", "https://magic.shyfai.cn/")


def asset_url_variants(value: str) -> tuple[str, ...]:
    """Match Magic's public edge and origin URLs for the same stored object.

    Callers must still scope the database lookup by both site and owner. Only
    these exact HTTPS asset prefixes are aliases; third-party URLs, query
    contents, arbitrary paths, ports and lookalike domains remain unchanged.
    """
    origin = "https://magic.shyfai.cn/image2-assets/"
    edge = "https://magic.shyfai.com/image2-assets/"
    for prefix, alias in ((origin, edge), (edge, origin)):
        if value.startswith(prefix):
            return value, alias + value[len(prefix):]
    return (value,)
