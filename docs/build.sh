#!/bin/sh
# Builds the GitHub Pages site into _site/ (or the directory given as $1) from the
# repo's own markdown, so the site never drifts from the README: pandoc renders each
# page through docs/template.html, and docs/links.lua points repo-relative links at
# the right page or the file on GitHub. Needs only pandoc.
set -eu

root="$(cd "$(dirname "$0")/.." && pwd)"
out="${1:-$root/_site}"

rm -rf "$out"
mkdir -p "$out/assets"
cp "$root/assets/logo.svg" "$out/assets/"

# page <source, relative to the repo> <output name> <title> [extra pandoc args...]
page() {
  src="$1" dest="$2" title="$3"
  shift 3
  pandoc "$root/$src" \
    --from gfm --to html5 --standalone \
    --template "$root/docs/template.html" \
    --lua-filter "$root/docs/links.lua" \
    --metadata pagetitle="$title" \
    --metadata source-dir="$(dirname "$src" | sed 's#^\.$##')" \
    "$@" \
    --output "$out/$dest"
  # Wide tables scroll inside their own box instead of the page.
  perl -0777 -i -pe 's#(<table\b.*?</table>)#<div class="table-scroll">$1</div>#gs' "$out/$dest"
  echo "built $dest"
}

page README.md index.html "robert" --toc --toc-depth=2 --metadata is-home=true
page cloud/README.md cloud.html "In the cloud" --toc --toc-depth=2 --metadata is-cloud=true
page CHANGELOG.md changelog.html "Changelog" --toc --toc-depth=2 --metadata is-changelog=true

touch "$out/.nojekyll"
