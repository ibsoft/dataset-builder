from datasetbuilder.markdown_utils import make_slug, parse_markdown, render_preview, build_markdown


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
