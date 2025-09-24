# Crestron Home integration for Home Assistant

This repository hosts a work-in-progress [Home Assistant](https://www.home-assistant.io/) custom integration for [Crestron Home](https://www.crestron.com/Products/Market-Solutions/Home-Solutions/Crestron-Home). Milestone 0 provides the foundational scaffold so the integration appears in Home Assistant's **Add Integration** list with a placeholder configuration flow.

> **Status:** Milestone 0 implements the integration shell only. No communication with Crestron Home systems is performed yet, and no devices or entities are created.

## Features

- Registers the `Crestron Home` integration (domain `crestron_home`) so it is discoverable in **Settings → Devices & Services → Add Integration**
- Placeholder config flow that immediately aborts with a friendly message while implementation work continues
- Passes [`hassfest`](https://developers.home-assistant.io/docs/creating_integration_manifest/#hassfest) validation to ensure the scaffold follows Home Assistant guidelines

## Installation

1. Copy the `custom_components/crestron_home` directory from this repository into your Home Assistant configuration folder under `custom_components/`.
2. Restart Home Assistant.
3. Navigate to **Settings → Devices & Services → Add Integration** and search for **Crestron Home**.
4. Select the integration to view the placeholder message. No configuration entries are stored yet.

## Development

Run hassfest locally to validate changes before committing:

```bash
pipx run hassfest --action validate --integration-path custom_components/crestron_home
```

Additional milestones will add the configuration flow, API client, and entity platforms.

## License

This project is licensed under the [MIT License](LICENSE).

