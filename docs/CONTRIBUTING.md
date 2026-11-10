# Contributing to Indus3D

Thanks for helping make Indus3D more useful for the Klipper community. Contributions of code, documentation, design feedback, simulator fixtures, and real-printer validation are all welcome.

## Before you begin

- Read the [project README](README.md) and [development notes](docs/DEVELOPMENT.md).
- Use simulation mode unless you understand the effect of every command sent to a real printer.
- Never commit `.env` files, private IP addresses, camera URLs, Tailscale names, API keys, or printer-specific credentials.
- Keep claims about automated quality control evidence-based. If a behaviour is theoretical, label it as such.

## Development setup

```bash
# Backend
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py --sim
```

```bash
# Frontend, in a second terminal
cd frontend
npm install
npm run dev
```

Run `npm run lint` and `npm run build` from `frontend/` before opening a pull request. For backend changes, verify the relevant Flask route or simulator scenario locally.

## Architecture rules

These rules protect the design and are not optional:

1. **The frontend must never call Moonraker directly.** Route all printer access through Flask `/api/printer/*` endpoints.
2. **Read configuration through `backend/config/settings.py`.** Do not add scattered `os.getenv()` calls or hard-coded IP addresses.
3. **Preserve simulator parity.** `SimulatedTelemetryWorker.latest` must retain the same shape as live telemetry.
4. **Preserve byte-offset alignment.** Changes to synthetic G-code or the visualizer must keep `file_position` aligned with UTF-8 G-code byte offsets.
5. **Make printer-changing commands explicit.** Explain the risk, use conservative defaults, and keep an auditable trail.

More context is available in [CLAUDE_CONTEXT.md](CLAUDE_CONTEXT.md).

## How to contribute

1. Check existing issues and discussions to avoid duplicate work.
2. Open an issue first for a substantial feature or a change that affects printer control.
3. Create a focused branch and keep the pull request small enough to review.
4. Add or update tests, simulator coverage, and documentation as appropriate.
5. Complete the pull-request checklist.

## Good first contributions

- Improve copy, accessibility, responsiveness, or visual consistency in the dashboard
- Add simulator shapes and regression fixtures
- Expand material or printer-profile documentation
- Improve API error states and empty states
- Add focused tests around the digital-twin models
- Report real-printer validation results with a reproducible configuration

See [docs/ROADMAP.md](docs/ROADMAP.md) for the wider roadmap.

## Reporting bugs

Use the bug-report template and include the Indus3D version/commit, whether the simulator or a real printer was used, the relevant logs, and safe reproduction steps. Never include secrets or public-facing machine addresses.

## Code of conduct

Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).
