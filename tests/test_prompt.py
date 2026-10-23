from pathlib import Path

PROMPT = (Path(__file__).parents[1] / 'teo' / 'prompt.md').read_text()


def test_prompt_keeps_verified_facts():
    for fact in (
        'Jong-Hoon Kim',
        'atrlab.kent@gmail.com',
        '@atrlab_kent',
        '@atr_lab',
        '241 Mathematical Sciences Building',
    ):
        assert fact in PROMPT


def test_prompt_never_names_the_handle_that_does_not_exist():
    assert '@atr_kent' not in PROMPT


def test_prompt_has_no_unfilled_placeholders():
    assert '[###]' not in PROMPT
    assert '[Lab phone]' not in PROMPT
