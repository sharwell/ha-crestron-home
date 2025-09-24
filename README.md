# Crestron Home integration for Home Assistant

This repository contains a custom [Home Assistant](https://www.home-assistant.io/) integration scaffold for controlling a Crestron Home system. Milestone 0 focuses on providing the initial project structure, including a placeholder config flow and automated validation.

## Installation

1. Copy `custom_components/crestron_home` into your Home Assistant configuration directory under `custom_components/`.
2. Restart Home Assistant.
3. Navigate to **Settings → Devices & Services → Add Integration** and search for **Crestron Home**.
4. The configuration flow currently aborts with a friendly message because no setup steps are implemented yet.

## Development

### Validate with hassfest

Run hassfest locally before committing changes:

```bash
pipx run hassfest --action validate --integration-path custom_components/crestron_home
```

### Future work

Milestone 1 will introduce communication with the Crestron Home API, authentication details, and an initial cover platform implementation.

## License

This project is released under the MIT License. See [LICENSE](LICENSE) for details.
