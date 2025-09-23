# Crestron Home – Home Assistant (Custom Integration)

**Milestone 0 (scaffold only).**  
This repository bootstraps a Home Assistant custom integration for Crestron Home. It includes:
- Standard file structure and config flow scaffolding
- Placeholders for API client and coordinator
- Pre-commit (Black + Ruff) and GitHub Actions (Ruff, Black, hassfest)
- MIT License

> **Not implemented yet**: login/auth, device discovery, entities, I/O. Those arrive in later milestones.

## Local install (manual)
Copy `custom_components/crestron_home` into your Home Assistant `/config/custom_components/` folder and restart Home Assistant. The integration will appear in *Settings → Devices & services → Integrations* (it won’t do anything yet—this is just scaffold).

## Repo layout
- `custom_components/crestron_home/` — integration package
- `config_flow.py` — minimal form; stores host/token/verify_ssl; does not call the network
- `api.py`, `coordinator.py`, `cover.py` — placeholders for future milestones
- `.pre-commit-config.yaml`, `pyproject.toml` — formatting & linting
- `.github/workflows/ci.yml` — CI with hassfest + lint

## Development
- Use Python 3.12+.
- Run `ruff` and `black` locally if available. Pre-commit is configured but optional.

## License
MIT
