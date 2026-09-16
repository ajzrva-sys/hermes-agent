"""File edits and substitution checks through the native worker transport."""
import base64

import pytest

pytestmark = pytest.mark.freebsd_only


def test_native_file_patch_binary_and_receipts(tmp_path):
    from tools.environments.freebsd_jail import FreeBSDJailEnvironment
    from tools.freebsd_jail_policy import project_policy
    project = tmp_path / "project"
    project.mkdir()
    env = FreeBSDJailEnvironment(str(project), policy=project_policy(
        str(project), home=tmp_path, profile=tmp_path / ".hermes"))
    try:
        env.init_session()
        files = env.file_operations()
        target = str(project / "hello.txt")
        result = files.write_file(target, "before\n")
        assert not result.error, result
        result = files.patch_replace(target, "before", "after")
        assert result.success, result
        assert files.read_file_raw(target).content == "after\n"
        import json
        notebook = project / "sample.ipynb"
        notebook.write_text(json.dumps({"nbformat": 4, "cells": [{"cell_type": "markdown", "source": ["Jailed document fixture"], "metadata": {}}]}))
        extracted, size = files.extract_document(str(notebook))
        assert "Jailed document fixture" in extracted and size == notebook.stat().st_size
        assert base64.b64decode(files.read_file_bytes(target).base64_content) == b"after\n"
        (project / "hello.txt").write_text("external change\n")
        result = files._atomic_write(target, "stale replacement\n")
        assert result.exit_code != 0
        assert (project / "hello.txt").read_text() == "external change\n"
    finally:
        env.cleanup()


def test_native_worker_rejects_symlinks_sockets_and_read_only_targets(tmp_path):
    from tools.environments.freebsd_jail import FreeBSDJailEnvironment
    from tools.freebsd_jail_policy import project_policy
    project = tmp_path / "project"
    project.mkdir()
    (project / "target").write_text("unchanged")
    (project / "alias").symlink_to("target")
    env = FreeBSDJailEnvironment(str(project), policy=project_policy(
        str(project), home=tmp_path, profile=tmp_path / ".hermes", read_only=True))
    try:
        files = env.file_operations()
        assert files.read_file_raw(str(project / "alias")).error
        assert files._atomic_write(str(project / "target"), "changed").exit_code != 0
        assert files.delete_file(str(project / "target")).error
        assert (project / "target").read_text() == "unchanged"
    finally:
        env.cleanup()
