# Security Policy

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security problems.

Report vulnerabilities privately to **narasimhadeshik@gmail.com** (or via
GitHub's [private security advisory](https://github.com/dvygo/MF-Engine/security/advisories/new)).
Include:

- a description of the issue and its impact,
- steps to reproduce (a minimal proof of concept if possible),
- affected file(s), phase, or configuration.

You can expect an acknowledgement within a few days. Please give us reasonable
time to investigate and ship a fix before any public disclosure.

## Scope

MF-Engine is a data pipeline, so the most relevant concerns are:

- **Credential handling** — API keys and MinIO credentials belong in `docker/.env`
  (gitignored) or environment variables, never committed. Report any leaked
  secret or a code path that logs one.
- **SSRF / injection** — the pipeline fetches URLs discovered from third-party
  sites; report cases where a crafted sitemap or page could make it fetch or
  execute something unintended.
- **Dependency vulnerabilities** — flag known CVEs in pinned dependencies.

## Responsible use

MF-Engine collects publicly available information. Using it to harvest data in
violation of a site's Terms of Service, applicable data-protection law, or for
unsolicited contact is outside its intended purpose and is the user's
responsibility.
