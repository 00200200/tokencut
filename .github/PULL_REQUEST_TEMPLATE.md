## Description
<!-- Briefly describe what changes you are introducing and the problem they solve. -->

## Type of Change
- [ ] 🚀 New feature (non-breaking change which adds token optimization capability)
- [ ] 🐛 Bug fix (non-breaking change which fixes an issue or edge case)
- [ ] ⚡ Performance improvement (reduces token burn or speeds up execution)
- [ ] 📚 Documentation update
- [ ] 🧪 Tests (adds or updates test suite)

## Verification & Benchmark
<!-- If adding a new compression filter, what are the before/after token numbers? -->
- **Raw tokens:**
- **Compacted tokens:**
- **Reduction %:**

## Checklist
- [ ] `uv run pytest -v` passes all tests.
- [ ] `uv run ruff check .` reports no lint errors.
- [ ] `uv run ruff format --check .` confirms correct formatting.
- [ ] Required diagnostics and recovery paths are tested; any unmeasured quality claims are identified.
- [ ] Documentation or README updated if applicable.
