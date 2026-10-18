# Security Policy

## Supported versions

Indus3D is under active development. Security fixes are applied to the current development version and included in the next stable public release.

## Reporting a vulnerability

Please do **not** open a public issue for a potential vulnerability, particularly one involving printer control, Moonraker access, camera streams, network exposure, or credentials.

Instead, contact the maintainer privately through the email address on the GitHub profile. Include:

- A clear description of the issue and affected component
- Reproduction steps or a proof of concept
- Potential impact
- Any suggested remediation

You should receive an acknowledgement within 7 days. Please allow time for a fix and coordinated disclosure before publishing details.

## Deployment guidance

- Keep Moonraker and the dashboard behind your trusted local network, VPN, or authenticated reverse proxy.
- Do not commit `.env` files or expose API tokens, camera URLs, or printer IP addresses.
- Review and test any automated correction command in simulation before enabling it on a physical printer.
