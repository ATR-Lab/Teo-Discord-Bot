from pathlib import Path

PROMPT = (Path(__file__).parents[1] / 'teo' / 'prompt.md').read_text()


def test_prompt_keeps_verified_facts():
    for fact in (
        'Jong-Hoon Kim',
        'atrlab.kent@gmail.com',
        '@atrlab_kent',
        '@atr_lab',
        '241 Mathematical Sciences Building',
        'Room 236',
        'Lab manager:** Marcus Arnett',
        'Lab safety contact:** Marcus Arnett',
        'https://discord.gg/NvwsANWEuw',
        'approved by the director on Nov. 5, 2026',
    ):
        assert fact in PROMPT


def test_prompt_explains_lab_board_deadlines():
    assert 'starts with "Deadline:"' in PROMPT
    assert 'create the event only after they confirm' in PROMPT
    assert 'Paper deadline' in PROMPT


def test_prompt_refuses_event_requests_up_front():
    assert '"Event permission:" line' in PROMPT
    assert 'say so right away' in PROMPT
    assert 'Anyone may still set a personal reminder' in PROMPT


def test_prompt_no_longer_calls_confirmed_facts_unconfirmed():
    assert 'awaiting the director' not in PROMPT
    assert "the lab's room number" not in PROMPT


def test_prompt_never_names_the_handle_that_does_not_exist():
    assert '@atr_kent' not in PROMPT


def test_prompt_has_no_unfilled_placeholders():
    assert '[###]' not in PROMPT
    assert '[Lab phone]' not in PROMPT
