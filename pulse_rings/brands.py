"""Offline Simple Icons registry, loaded only on first use and once per process."""
import difflib
from functools import lru_cache
import json
from pathlib import Path


@lru_cache(maxsize=1)
def _brands():
    return json.loads(Path(__file__).with_name('brands.json').read_text(encoding='utf-8'))


def has_brand(slug):
    return isinstance(slug, str) and slug in _brands()


def suggest(slug):
    if not isinstance(slug, str):
        return None
    matches = difflib.get_close_matches(slug, _brands(), n=1)
    return matches[0] if matches else None


def search(query, limit=10):
    """Bounded slug/title search: exact, substring, then fuzzy; never artwork."""
    if not isinstance(query, str) or not 1 <= len(query) <= 80 or not query.strip():
        raise ValueError('brand_query must be 1–80 nonblank characters.')
    query = query.strip().casefold()
    records = _brands()
    names = {slug: (slug.casefold(), record['title'].casefold()) for slug, record in records.items()}
    direct = sorted((slug for slug, fields in names.items() if any(query in field for field in fields)),
                    key=lambda slug: (query not in names[slug], not names[slug][0].startswith(query), slug))
    labels = {label: slug for slug, fields in names.items() for label in fields}
    fuzzy = [labels[label] for label in difflib.get_close_matches(query, sorted(labels), n=20, cutoff=0.6)]
    slugs = list(dict.fromkeys(direct + fuzzy))[:min(10, max(0, limit))]
    return [{'slug': slug, 'title': records[slug]['title']} for slug in slugs]


def brand(slug):
    value = _brands().get(slug) if isinstance(slug, str) else None
    return dict(value) if value is not None else None
