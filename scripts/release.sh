#!/usr/bin/env bash
# Cuts a release: bumps version, dates the CHANGELOG entry,
# commits, tags `vX.Y.Z`, and pushes. The `publish.yml` workflow
# then builds, publishes to PyPI, and creates the GitHub release.
#
# Usage: scripts/release.sh <version>
# Example: scripts/release.sh 0.2.1

set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: $0 <version>" >&2
  echo "Example: $0 0.2.1" >&2
  exit 1
fi

version="$1"
tag="v$version"
today="$(date -u +%Y-%m-%d)"

if ! [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([a-zA-Z0-9.+-]*)?$ ]]; then
  echo "Invalid version: $version" >&2
  exit 1
fi

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Working tree is dirty. Commit or stash changes first." >&2
  exit 1
fi

current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [ "$current_branch" != "main" ]; then
  echo "Not on main (currently on $current_branch)." >&2
  exit 1
fi

if git rev-parse "$tag" >/dev/null 2>&1; then
  echo "Tag $tag already exists." >&2
  exit 1
fi

echo "Fetching latest main..."
git pull --ff-only

python3 - "$version" <<'PY'
import pathlib, re, sys
version = sys.argv[1]

pyproject = pathlib.Path("pyproject.toml")
text = pyproject.read_text()
new = re.sub(
    r'(?m)^version\s*=\s*"[^"]+"',
    f'version = "{version}"',
    text,
    count=1,
)
if new == text:
    sys.exit("Could not update version in pyproject.toml")
pyproject.write_text(new)

init = pathlib.Path("src/kurrent_sqlalchemy/__init__.py")
text = init.read_text()
new = re.sub(
    r'(?m)^__version__\s*=\s*"[^"]+"',
    f'__version__ = "{version}"',
    text,
    count=1,
)
if new == text:
    sys.exit("Could not update __version__ in src/kurrent_sqlalchemy/__init__.py")
init.write_text(new)
PY

python3 - "$version" "$today" <<'PY'
import pathlib, sys
version, today = sys.argv[1], sys.argv[2]
path = pathlib.Path("CHANGELOG.md")
text = path.read_text()
needle = f"## [{version}] - Unreleased"
replacement = f"## [{version}] - {today}"
if needle not in text:
    sys.exit(
        f"CHANGELOG.md has no '{needle}' section. "
        f"Add one (or rename the existing Unreleased section) before releasing."
    )
path.write_text(text.replace(needle, replacement, 1))
PY

echo
echo "Staged release changes:"
git --no-pager diff -- pyproject.toml src/kurrent_sqlalchemy/__init__.py CHANGELOG.md
echo

read -r -p "Commit, tag $tag, and push? [y/N] " ans
case "$ans" in
  y|Y|yes|YES) ;;
  *)
    echo "Aborted. Changes left in the working tree."
    exit 1
    ;;
esac

git add pyproject.toml src/kurrent_sqlalchemy/__init__.py CHANGELOG.md
git commit -m "Release $tag"
git tag -a "$tag" -m "Release $tag"
git push origin main
git push origin "$tag"

echo
echo "Pushed $tag. The publish workflow will build, upload to PyPI, and create the GitHub release."
echo "Watch it with: gh run watch"
