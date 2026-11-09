# Secret checks

The commit hook and CI use Gitleaks v8.24.2 with the same repository configuration.
Output is redacted. CI scans full reachable history on pushes and pull requests.

Install Go (1.24 or newer), then enable the hook in your checkout:

```sh
python3 -m pip install pre-commit
pre-commit install
pre-commit run gitleaks --all-files
```

For a full history scan with the pinned command-line scanner:

```sh
go install github.com/zricethezav/gitleaks/v8@v8.24.2
gitleaks git --redact --no-banner --log-opts="--all"
python3 tools/security/test_secret_scanning.py
```

The scanner extends the default rules with Telegram bot-token detection. Its two exact-line
allowlists cover a browser preference storage name and the public RFC 6455 handshake nonce,
not credentials. Historical test fixtures are suppressed only by exact commit/path/rule/line
fingerprints in `.gitleaksignore`; no test directory or entire commit is exempt.

Never paste a real token into a test. Assemble synthetic values at runtime when testing
credential detection. Do not add broad exclusions to silence an unexpected finding.

If a real credential is committed, revoke or rotate it first. Removing it in a later commit
does not remove it from history, clones or caches. Review history cleanup separately and
do not dismiss an alert as test data unless its provenance is established.

Local hooks must be installed in each checkout. CI runs after these files are pushed;
maintainers should make the Secret checks job a required branch-protection check.
