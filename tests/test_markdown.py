from datasetbuilder.markdown_utils import make_slug, parse_markdown, render_preview, build_markdown
import pytest


def test_slug_preserves_greek_and_strips_path():
    assert make_slug('Απώλεια Επικοινωνίας / kiosk') == 'Απώλεια_Επικοινωνίας_kiosk'
    assert '/' not in make_slug('../dangerous\\path')
    assert len(make_slug('世' * 200).encode('utf-8')) <= 170


def test_original_sample_procedures_are_preserved():
    from pathlib import Path
    raw=(Path(__file__).parent.parent/'examples'/'TC-KB-001-Kiosk-Communication-Lost.md').read_text(encoding='utf-8')
    parsed=parse_markdown(raw)
    assert parsed['title']=='Kiosk Communication Lost'
    assert parsed['metadata']['Product']=='TotalCare'
    assert len(parsed['sections'])>=8
    diag=next(s for s in parsed['sections'] if s['title']=='DIAGNOSTIC PROCEDURE')
    assert '### Step 6: Identify the Most Likely Cause' in diag['body']
    corrective=next(s for s in parsed['sections'] if s['title']=='CORRECTIVE ACTIONS')
    assert '### Cause: Network Connectivity Failure' in corrective['body']


def test_markdown_builder_multiple_solutions():
    text=build_markdown('Test','TC-KB-22',{'Product':'TotalCare'},'',
        [{'title':'CORRECTIVE ACTIONS','body':'Do the following.'}],
        [{'title':'Option A','body':'1. First'},{'title':'Option B','body':'1. Second'}])
    assert text.index('## SOLUTIONS')>text.index('## CORRECTIVE ACTIONS')
    assert '### Solution 2: Option B' in text


def test_preview_html_sanitized():
    html=render_preview('# Hello\n\n<img src="javascript:evil()" onerror="alert(1)">')
    assert 'onerror=' not in html
    assert 'javascript:' not in html


def test_preview_renders_markdown_images_and_sanitizes_unsafe_sources():
    html = render_preview(
        '![Image description](https://example.com/image.png "Image title")\n\n'
        '![Local](/static/example.png)\n\n'
        '![Unsafe](javascript:alert(1))\n\n'
        '<img src="https://example.com/x.png" onerror="alert(1)">'
    )
    assert '<img alt="Image description" src="https://example.com/image.png" title="Image title">' in html
    assert '<img alt="Local" src="/static/example.png">' in html
    assert 'javascript:' not in html
    assert 'onerror' not in html


@pytest.mark.parametrize('url', [
    'https://youtu.be/fetYOHyWbY0',
    'https://www.youtube.com/watch?v=fetYOHyWbY0',
    'https://youtube.com/shorts/fetYOHyWbY0',
    'https://m.youtube.com/embed/fetYOHyWbY0',
])
def test_youtube_media_renders_player(url):
    html = render_preview(f'![TMA Agent Configuration](media:{url}  )')
    assert 'src="https://www.youtube-nocookie.com/embed/fetYOHyWbY0"' in html
    assert 'title="TMA Agent Configuration"' in html


@pytest.mark.parametrize('url', [
    'http://youtu.be/fetYOHyWbY0', 'https://youtube.com.evil.test/watch?v=fetYOHyWbY0',
    'https://youtube.com@evil.test/watch?v=fetYOHyWbY0',
    'https://youtu.be/invalid', 'javascript:alert',
])
def test_invalid_media_remains_text_without_player(url):
    html = render_preview(f'![Example](media:{url})')
    assert '<iframe' not in html
    assert '![Example](media:' in html


def test_media_markup_does_not_bypass_sanitization_or_code_blocks():
    html = render_preview(
        '![&quot; onload=&quot;bad](media:https://youtu.be/fetYOHyWbY0)\n\n'
        '<iframe src="https://evil.test"></iframe>\n\n'
        '`![code](media:https://youtu.be/fetYOHyWbY0)`\n\n'
        '```\n![code](media:https://youtu.be/fetYOHyWbY0)\n```'
    )
    assert html.count('<iframe ') == 1
    assert 'src="https://evil.test"' not in html
    assert '<code>![code](media:https://youtu.be/fetYOHyWbY0)</code>' in html
    assert 'title="&amp;quot; onload=&amp;quot;bad"' in html
