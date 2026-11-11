"""Demo copy regressions N13/N14."""
import pytest

from pulse_rings.engine import compute_capsule, compute_lines


@pytest.mark.parametrize('word', ['turns', 'items', 'issues', 'members', 'channels', 'stars', 'forks', 'PRs', 'subagents'])
def test_one_is_singular_in_capsule_and_lines(word):
    definition = {'capsule': {'metric': 'n', 'label': '{value} ' + word, 'fill': 'none'},
                  'lines': [{'metric': 'n', 'label': '{value} ' + word}]}
    current = {'metrics': {'n': 1}}
    ring = {'components': []}
    assert compute_capsule(definition, current, ring)['label'] == '1 ' + word[:-1]
    assert compute_lines(definition, current, ring)[0]['label'] == '1 ' + word[:-1]


def test_ratio_caption_is_one_decimal_not_false_precision():
    definition = {'capsule': {'metric': 'n', 'label': '{value} PRs', 'fill': 'baseline'}}
    current = {'metrics': {'n': 170}}
    ring = {'components': [{'metric': 'n', 'baseline': 794 / 14}]}
    assert compute_capsule(definition, current, ring)['caption'] == '3.0× usual'
