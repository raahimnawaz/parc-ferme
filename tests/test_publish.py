import json
import subprocess

import pytest

from parc_ferme.site.publish import PublishError, publish


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A committed repo with a bare remote, and a built site outside the repo."""
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--quiet", "--bare", str(remote))
    work = tmp_path / "work"
    work.mkdir()
    git(work, "init", "--quiet", "-b", "main")
    git(work, "config", "user.email", "test@example.com")
    git(work, "config", "user.name", "Test")
    (work / "README.md").write_text("code\n")
    git(work, "add", "README.md")
    git(work, "commit", "--quiet", "-m", "code")
    git(work, "remote", "add", "origin", str(remote))
    site = tmp_path / "site"
    (site / "2026" / "01-test-race").mkdir(parents=True)
    (site / "index.html").write_text("<p>index</p>")
    (site / ".nojekyll").write_text("")
    (site / ".DS_Store").write_text("finder")
    page = site / "2026" / "01-test-race"
    (page / "index.html").write_text("<p>page</p>")
    (page / "debrief.json").write_text(json.dumps({"code": {"commit": "abc", "dirty": False}}))
    return work, remote, site


def test_publish_puts_the_site_on_its_own_branch(repo):
    work, remote, site = repo
    commit = publish(site, work)
    files = git(remote, "ls-tree", "-r", "--name-only", "gh-pages").splitlines()
    assert set(files) == {".nojekyll", "index.html", "2026/01-test-race/index.html", "2026/01-test-race/debrief.json"}
    assert git(remote, "rev-parse", "gh-pages") == commit
    assert git(work, "rev-parse", "--abbrev-ref", "HEAD") == "main"


def test_an_unchanged_site_is_not_published_again(repo):
    work, remote, site = repo
    first = publish(site, work)
    assert publish(site, work) is None
    (site / "index.html").write_text("<p>index, updated</p>")
    second = publish(site, work)
    assert git(remote, "rev-parse", f"{second}^") == first


def test_uncommitted_code_or_pages_are_refused(repo):
    work, _, site = repo
    (work / "README.md").write_text("changed\n")
    with pytest.raises(PublishError, match="uncommitted changes"):
        publish(site, work)
    git(work, "checkout", "--", "README.md")
    (site / "2026" / "01-test-race" / "debrief.json").write_text(json.dumps({"code": {"dirty": True}}))
    with pytest.raises(PublishError, match="built from uncommitted code"):
        publish(site, work)
