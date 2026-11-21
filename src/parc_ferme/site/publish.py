"""Publish the built site to the branch GitHub Pages serves, without touching the working tree.

The pages are committed onto that branch with git plumbing and a throwaway index, so publishing never switches
branches or disturbs uncommitted work. A publish is refused when the code isn't committed, or when any page was
built from uncommitted code: every published number has to trace back to a commit.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

BRANCH = "gh-pages"


class PublishError(RuntimeError):
    pass


def _git(repo: Path, *args: str, env: dict | None = None, check: bool = True) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, env=env)
    if check and r.returncode:
        raise PublishError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def preflight(site: Path, repo: Path) -> str:
    """The short commit the site is published from. Raises if the site or the code isn't fit to publish."""
    if not (site / "index.html").exists():
        raise PublishError(f"no site at {site}: run `parc-ferme site` first")
    if _git(repo, "status", "--porcelain", "--untracked-files=no"):
        raise PublishError("the code has uncommitted changes: commit them, rebuild, then publish")
    for doc in site.glob("*/*/debrief.json"):
        code = json.loads(doc.read_text()).get("code", {})
        if code.get("dirty"):
            raise PublishError(f"{doc.parent.name} was built from uncommitted code: "
                               "rebuild it with `parc-ferme debrief`")
    return _git(repo, "rev-parse", "--short", "HEAD")


def publish(site: Path, repo: Path, remote: str = "origin", branch: str = BRANCH) -> str | None:
    """Commit the contents of `site` as the new tip of `branch` on `remote` and push it. Returns the new commit,
    or None when the site is unchanged since the last publish."""
    source = preflight(site, repo)
    _git(repo, "fetch", "--quiet", remote, branch, check=False)
    parent = _git(repo, "rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{branch}", check=False)
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        _git(repo, f"--work-tree={site}", "add", "--all", "--", ".", ":(exclude,glob)**/.DS_Store", env=env)
        tree = _git(repo, "write-tree", env=env)
    if parent and _git(repo, "rev-parse", f"{parent}^{{tree}}") == tree:
        return None
    args = ["commit-tree", tree, "-m", f"Publish the debriefs, built from {source}"]
    if parent:
        args += ["-p", parent]
    commit = _git(repo, *args)
    _git(repo, "push", "--quiet", remote, f"{commit}:refs/heads/{branch}")
    _git(repo, "fetch", "--quiet", remote, branch, check=False)
    return commit
