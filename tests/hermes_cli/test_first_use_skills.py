"""New users of a shared installation get an independent bundled skill library."""

import json
from pathlib import Path

import pytest

from hermes_cli import config


def _bundle(tmp_path):
    bundle = tmp_path / 'bundled'
    for name in ('hermes-agent', 'first-use-demo'):
        skill = bundle / 'general' / name
        skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text(
            f'---\nname: {name}\ndescription: A bootstrap test skill.\n---\n'
            'Use the bundled reference.\n', encoding='utf-8',
        )
        reference = skill / 'references' / 'usage.md'
        reference.parent.mkdir()
        reference.write_text('Bundled reference.\n', encoding='utf-8')
    return bundle


def test_first_use_seeds_each_home_without_inheriting_or_replacing_state(tmp_path, monkeypatch):
    bundle = _bundle(tmp_path)
    monkeypatch.setenv('HERMES_BUNDLED_SKILLS', str(bundle))
    homes = [tmp_path / 'first-user' / '.hermes', tmp_path / 'second-user' / 'custom-home']
    for home in homes:
        home.mkdir(parents=True)
        user_config = home / 'config.yaml'
        user_config.write_text('display:\n  compact: true\n', encoding='utf-8')
        soul = home / 'SOUL.md'
        soul.write_text('Keep this user persona.\n', encoding='utf-8')
        config_before, soul_before = user_config.read_bytes(), soul.read_bytes()
        monkeypatch.setenv('HERMES_HOME', str(home))
        config.load_config()
        for source in bundle.rglob('*'):
            if source.is_file():
                destination = home / 'skills' / source.relative_to(bundle)
                assert destination.is_file(), f'First use did not seed {destination}'
                assert destination.read_bytes() == source.read_bytes()
        assert user_config.read_bytes() == config_before
        assert soul.read_bytes() == soul_before
        assert not (home / '.env').exists()
        assert not (home / 'auth.json').exists()

    first_skill = homes[0] / 'skills/general/first-use-demo/SKILL.md'
    first_skill.write_text('User-owned customization.\n', encoding='utf-8')
    assert (homes[1] / 'skills/general/first-use-demo/SKILL.md').read_bytes() != first_skill.read_bytes()


@pytest.mark.parametrize('opted_out', [False, True])
def test_first_use_respects_opt_out_and_keeps_user_edits_and_deletions(tmp_path, monkeypatch, opted_out):
    bundle = _bundle(tmp_path)
    home = tmp_path / 'user-home'
    home.mkdir()
    monkeypatch.setenv('HERMES_HOME', str(home))
    monkeypatch.setenv('HERMES_BUNDLED_SKILLS', str(bundle))
    if opted_out:
        (home / '.no-bundled-skills').touch()

    config.load_config()
    essential = home / 'skills/general/hermes-agent/SKILL.md'
    other = home / 'skills/general/first-use-demo/SKILL.md'
    assert essential.is_file()
    assert other.exists() is not opted_out
    essential.write_text('User customization survives startup.\n', encoding='utf-8')
    if other.exists():
        other.unlink()
    manifest = home / 'skills/.bundled_manifest'
    recorded_manifest = manifest.read_bytes()

    # Exercise another initialization rather than the process-local memo fast path.
    monkeypatch.setattr(config, '_HERMES_HOME_ENSURED', set())
    config.load_config()
    assert essential.read_text() == 'User customization survives startup.\n'
    assert not other.exists()
    assert manifest.read_bytes() == recorded_manifest


@pytest.mark.parametrize('relative', [
    'first-use-demo/SKILL.md',
    'personal/first-use-demo/SKILL.md',
    'personal/alias/SKILL.md',
    'first-use-demo.md',
])
@pytest.mark.parametrize('name_value', [
    'first-use-demo',
    'first-use-demo # user alias',
    '>-\n  first-use-demo',
])
def test_first_use_keeps_existing_skill_name_resolution(tmp_path, monkeypatch, relative, name_value):
    bundle = _bundle(tmp_path)
    home = tmp_path / 'user-home'
    original = home / 'skills' / relative
    original.parent.mkdir(parents=True)
    content = (f'---\nname: {name_value}\ndescription: A user-owned skill.\n---\n'
               'Keep this custom workflow.\n')
    original.write_text(content, encoding='utf-8')
    monkeypatch.setenv('HERMES_HOME', str(home))
    monkeypatch.setenv('HERMES_BUNDLED_SKILLS', str(bundle))

    config.load_config()
    from tools.skills_tool import skill_view
    from tools.skills_sync import sync_skills

    for _ in range(2):
        loaded = json.loads(skill_view('first-use-demo', preprocess=False))
        assert loaded['success'], loaded.get('error')
        assert Path(loaded['_source_path']) == original
        assert original.read_text() == content
        assert not (home / 'skills/general/first-use-demo').exists()
        assert (home / 'skills/general/hermes-agent/SKILL.md').is_file()
        sync_skills(quiet=True)
