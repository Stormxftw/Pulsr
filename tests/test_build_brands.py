"""Reproducible brand build from inert archives; no JS execution or network."""
import importlib.util
import io
import json
from pathlib import Path
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location('build_brands_test', ROOT / 'scripts/build-brands.py')
builder = importlib.util.module_from_spec(loader)
loader.loader.exec_module(builder)


def archive(path, *, slug='safe', title='Safe', source='https://example.org/art'):
    files = {
        'package.json': json.dumps({'name': 'simple-icons', 'version': 'test-release', 'license': 'CC0-1.0'}),
        'data/simple-icons.json': json.dumps([{'title': 'Safe', 'hex': 'ABCDEF'}, {'title': 'Unsafe', 'hex': '000000'}]),
        'icons/safe.svg': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><title>Safe</title><path d="M0 0h24v24H0z"/></svg>',
        'icons/unsafe.svg': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><title>Unsafe</title><path d="M0 0url(script)"/></svg>',
        'LICENSE.md': 'CC0 upstream fixture', 'DISCLAIMER.md': 'Trademark disclaimer fixture',
    }
    files['data/simple-icons.json'] = json.dumps([
        {'title': title, 'hex': 'ABCDEF', 'source': source}, {'title': 'Unsafe', 'hex': '000000'}])
    files['icons/' + slug + '.svg'] = files.pop('icons/safe.svg').replace('<title>Safe</title>', '<title>' + title + '</title>')
    with tarfile.open(path, 'w:gz') as tar:
        for name, text in files.items():
            data = text.encode()
            item = tarfile.TarInfo('package/' + name)
            item.size = len(data)
            tar.addfile(item, io.BytesIO(data))
    return path


def test_builder_drops_unsafe_paths_reports_and_preserves_notices(tmp_path, capsys):
    source = archive(tmp_path / 'release.tgz')
    result = builder.build(source, tmp_path / 'first')
    assert result['input_count'] == 2 and result['accepted'] == 1 and result['dropped'] == ['unsafe']
    assert json.loads(capsys.readouterr().out)['dropped'] == ['unsafe']
    data = json.loads((tmp_path / 'first/brands.json').read_text())
    assert data == {'safe': {'title': 'Safe', 'hex': 'ABCDEF', 'path': 'M0 0h24v24H0z'}}
    legal = (tmp_path / 'first/BRANDS-LICENSE.md').read_text()
    assert 'test-release' in legal and 'CC0 upstream fixture' in legal and 'Trademark disclaimer fixture' in legal
    builder.build(source, tmp_path / 'second')
    for name in ('brands.json', 'BRANDS-LICENSE.md'):
        assert (tmp_path / 'first' / name).read_bytes() == (tmp_path / 'second' / name).read_bytes()


def test_builder_oversize_stops_without_overwriting_any_output(tmp_path, monkeypatch, capsys):
    source = archive(tmp_path / 'release.tgz')
    output = tmp_path / 'output'
    output.mkdir()
    (output / 'brands.json').write_bytes(b'original')
    (output / 'BRANDS-LICENSE.md').write_bytes(b'original licence')
    monkeypatch.setattr(builder, 'LIMIT', 1)
    with pytest.raises(SystemExit, match='exceeds byte cap'):
        builder.build(source, output)
    assert json.loads(capsys.readouterr().out)['bytes'] > 1
    assert (output / 'brands.json').read_bytes() == b'original'
    assert (output / 'BRANDS-LICENSE.md').read_bytes() == b'original licence'


@pytest.mark.parametrize('slug,title,source,reason', [
    ('monero', 'Neutral', 'https://example.org/art', 'crypto_mining'),
    ('neutral', 'Monero', 'https://example.org/art', 'crypto_mining'),
    ('neutral', 'Neutral', 'https://ngrok.com/logo', 'tunnel_service')])
def test_builder_excludes_slug_title_or_source_and_records_every_reason(tmp_path, slug, title, source, reason):
    report = builder.build(archive(tmp_path / 'release.tgz', slug=slug, title=title, source=source), tmp_path / 'out')
    assert report['excluded'] == [{'slug': slug, 'reasons': [reason]}]
    assert report['accepted'] == 0 and report['dropped'] == ['unsafe']
    assert json.loads((tmp_path / 'out/brands.json').read_text()) == {}
    legal = (tmp_path / 'out/BRANDS-LICENSE.md').read_text(encoding='utf-8')
    assert f'Excluded slug `{slug}`' in legal and reason in legal and 'ARTWORK SCOPE' in legal


def test_artwork_scope_source_pattern_changes_apply_at_build_time(tmp_path, monkeypatch):
    source = tmp_path / 'hermes/tools'; source.mkdir(parents=True)
    # Inert fixture scanner AST; never imported/executed by the builder.
    (source / 'skills_guard.py').write_text("THREAT_PATTERNS = [('newbrand', 'crypto_mining'), ('otherbrand', 'tunnel_service')]", encoding='utf-8')
    monkeypatch.setenv('HERMES_SOURCE', str(source.parent))
    assert builder.artwork_patterns() == {'crypto_mining': 'newbrand', 'tunnel_service': 'otherbrand'}
    report = builder.build(archive(tmp_path / 'release.tgz', slug='newbrand'), tmp_path / 'out')
    assert report['excluded'] == [{'slug': 'newbrand', 'reasons': ['crypto_mining']}]


def test_brand_api_loads_once_and_returns_defensive_copy():
    from pulse_rings import brands
    data = brands._brands()
    assert brands.has_brand('github') and brands.suggest('githb') == 'github'
    assert brands._brands() is data
    value = brands.brand('github')
    value['path'] = '<script>'
    assert brands.brand('github')['path'] != '<script>'
