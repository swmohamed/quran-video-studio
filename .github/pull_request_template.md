## What changed

<!-- Brief summary of the change -->

## Why

<!-- The problem this solves, or the link to a related issue -->

## Testing performed

<!-- What you ran and what you saw. For pipeline changes: which reciter/range
     was rendered, and which test scripts passed. -->

## Checklist

- [ ] The change is focused — no unrelated modifications included
- [ ] Frontend type-checks (`cd frontend && npx tsc -b`)
- [ ] **Video/audio pipeline change** — ran a real render
      (`backend/tests/e2e_render.py`) and `verify_continuous.py`, and watched
      the produced MP4
- [ ] **UI change** — attached before/after screenshots
- [ ] **Quran text / translation / recitation audio / timing change** — used a
      verifiable source (stated below) and tested multi-ayah render + sync

<!-- If this PR touches Quran data or audio, state the exact source used. -->
