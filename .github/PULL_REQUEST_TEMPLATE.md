<!-- Thanks for contributing to MF-Engine! Keep PRs small and focused. -->

## Summary

<!-- What does this change do, and why? -->

Fixes #<!-- issue number, if any -->

## Type of change

- [ ] Bug fix
- [ ] New AMC / domain mapping / verified LinkedIn override
- [ ] Phase improvement (parsing, classification, backend, WAF handling)
- [ ] Refactor (no behavior change)
- [ ] Docs / tests
- [ ] Other:

## How it was tested

<!-- Which phase did you run, and what did the output look like? Paste the
relevant log line or a few rows of the output file. "It compiles" is not
enough — exercise the affected phase end-to-end. -->

## Checklist

- [ ] `python -m py_compile` passes on changed files
- [ ] Ran the affected phase end-to-end and verified the output file
- [ ] Respects the [project principles](../CONTRIBUTING.md#project-principles-please-read):
      no fabricated URLs, degrades gracefully, guesses never asserted as fact, public data only
- [ ] Updated `context/` docs / `README.md` if behavior or schema changed
- [ ] Self-reviewed the diff and considered edge cases (bot-blocked sites, empty results, redirects)

## AI assistance

- [ ] This PR was written with help from an AI tool
- [ ] I have read and understood **every line** I'm submitting and can explain it
- [ ] I verified any API fields, function names, and URLs against reality (not the model's confidence)
