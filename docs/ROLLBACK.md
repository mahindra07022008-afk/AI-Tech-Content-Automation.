# Rollback guide — editing-style upgrade

The editing-style upgrade (12 styles, real-time 3D phone, PixiJS pixel art, isometric visuals, auto style
selection, lite render profile, 60 fps option, new QA checks) lives on branch `ccr-d84b1eb7-6e6n50`
and reaches `main` only through its pull request. The last version before it is:

| Ref | Commit | What it is |
|---|---|---|
| `main` before this upgrade | `163c851` | Premium editor (Remotion + FFmpeg) + code auto-fit fix, verified |

## Option 1 — don't merge (nothing to roll back)
`main` is untouched until you merge the PR. Close the PR if you don't want the upgrade.

## Option 2 — after merging, switch behaviour off without touching code
Styles are additive. To get the previous look on new videos:
```bash
telugu-tech premium generate --storyboard FILE --style ai_news   # closest to the old house preset
# or keep the previous engine entirely:
telugu-tech generate-short --storyboard FILE --engine classic
```
Storyboards without the new visual types (`phone3d`, `pixel_scene`, `iso_stack`) render exactly as before
except for the chosen style's palette/overlay.

## Option 3 — after merging, revert the merge commit
```bash
git checkout main && git pull
git log --oneline -3                       # find the "Merge pull request #N …" commit of this upgrade
git revert -m 1 <merge-commit-sha>         # creates a new commit that undoes the upgrade
git push origin main
cd remotion && npm ci && cd ..             # restores the previous node_modules from the old lockfile
```

## Option 4 — inspect or run the previous version side by side
```bash
git worktree add ../tt-previous 163c851
cd ../tt-previous && uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python -e ".[youtube,dev]"
cd remotion && npm ci
```

Nothing in this upgrade touches YouTube OAuth tokens, Gmail settings, scheduler state or `data/`
(all gitignored), so a rollback never affects credentials or past videos.
