"""CI Test Remediation Phase 1 — process-tempdir isolation regression.

Encodes the GitHub-CI failure mechanism and its conftest fix: the
vendored Hermes runtime's boot hook repoints the PROCESS-GLOBAL temp
state (TMPDIR + tempfile.tempdir) at a per-job scratch directory; once
that directory is removed, bare tempfile creation in ANY later test
fails. The autouse ``_isolate_process_tempdir`` conftest fixture must
restore the process temp state between tests so the leak cannot cross
a test boundary — exactly what the 52 CI failures (i7/i8/i11/image-
validator suites) violated.

The two tests are order-dependent BY DESIGN: the first performs the
leak, the second proves the isolation. Offline; no providers.
"""
import os
import tempfile
from pathlib import Path


def test_leak_simulator_hermes_scratch_repoint():
    """Simulate the Hermes boot-hook side effect: repoint the process
    temp state at a scratch directory and then REMOVE it (the job-cache
    lifetime). Bare tempfile creation inside THIS test then fails —
    the exact CI error signature."""
    scratch = Path(tempfile.mkdtemp(prefix="hermes-leak-sim-"))
    os.environ["TMPDIR"] = str(scratch)
    tempfile.tempdir = None  # force re-derivation from TMPDIR
    assert Path(tempfile.gettempdir()) == scratch

    scratch.rmdir()  # the job scratch dies with the job

    try:
        tempfile.mkstemp(prefix="post-leak-")
        raised = False
    except FileNotFoundError:
        raised = True
    finally:
        tempfile.tempdir = None  # do not cache the dead directory
    assert raised, "leak simulation must reproduce the CI FileNotFoundError"


def test_bare_tempfile_works_after_leaky_test():
    """After a test that leaked (and whose scratch directory was
    removed), a bare tempfile.mkstemp() must work again: the conftest
    isolation fixture restored the process temp state at the previous
    test's boundary. Without the fix, this is FileNotFoundError into
    the deleted hermes scratch directory (the 52 CI failures)."""
    fd, path = tempfile.mkstemp(prefix="post-isolation-")
    try:
        assert Path(path).exists()
        # The restored default temp dir is a live directory, not the
        # removed hermes scratch from the previous test.
        assert Path(tempfile.gettempdir()).is_dir()
    finally:
        os.close(fd)
        os.unlink(path)
