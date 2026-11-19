# Crestron Home integration for Home Assistant

Control Crestron Home shades from Home Assistant. Each shade appears as a cover
with position and availability. You can open, close, stop, or set its position,
calibrate how far it opens at each percentage, and group shades for coordinated
stops.

## Installation

Home Assistant needs network access to the Crestron Home controller and a Web API
token. To install with HACS, add
[`sharwell/ha-crestron-home`](https://github.com/sharwell/ha-crestron-home)
as a custom repository of type **Integration**. Download **Crestron Home** in
HACS, then restart Home Assistant. [HACS custom repository instructions](https://www.hacs.xyz/docs/faq/custom_repositories/)

## Configuration

1. On the Crestron controller, go to **Settings → System Control Options → Web API Settings**
   and create a long-lived Web API token.
2. In Home Assistant, go to **Settings → Devices & services → Add integration** and
   select **Crestron Home**.
3. Enter the controller host and API token. Leave SSL certificate verification
   enabled unless the controller uses a self-signed certificate.
4. Submit to test the connection. Confirm the number of rooms the controller
   reports to finish setup.

To change integration options, open **Settings → Devices & services → Crestron
Home** and select **Configure** on the integration entry.

## Shade control

Use the cover controls or the `cover.open_cover`, `cover.close_cover`,
`cover.set_cover_position`, and `cover.stop_cover` actions. A shade the controller
reports as offline appears unavailable. The integration polls approximately every
12 seconds while idle and polls faster after successful writes.

Commands queued within the 80 ms batching window can share a controller request,
with up to 16 shades per request. If several targets for one shade are queued
before the request is sent, the latest target wins.

### Stop and hold-to-move

**Predictive Stop** is enabled by default. It estimates where moving shades will
stop using learned travel speed, command latency, and deceleration. Stop is
best effort because the Crestron REST API lacks a native stop command.

If you turn off **Options → Predictive Stop**, Stop sends the latest known
position back to the controller. It skips a shade when there is no known
position. To clear learned parameters, open **Options → Reset learned
parameters** and select the shade. The model learns again as the shade moves.

The [Matter hold/release blueprint](blueprints/automation/crestron_home/matter_shade_hold_release.yaml)
lets you hold a wall-switch button to open or close selected shades and release it
to stop them. Choose the Matter device and the matching hold and release device
triggers for each button.

### Visual groups

Use **Options → Visual groups** to put shades that should finish together in the
same group. With no explicit groups, Predictive Stop treats all shades as one
group for alignment. Once groups are configured, Predictive Stop aligns shades
within each group, and unassigned shades are handled independently.

## Calibration

Under **Options → Global defaults**, enable **Invert shade position** if the
controller reports 0% as fully open. Each shade can follow that default or
override it with its own **Invert axis** setting. The integration applies each
shade's calibration to both reported positions and position commands.

- **Calibrate a shade** maps Home Assistant percentages to Crestron positions in
  the 0–65535 range. Keep the 0% and 100% anchors, put intermediate percentages in
  ascending order, and use raw values that stay the same or increase. Add or
  remove interior anchors as needed, or select **Reset to defaults** to restore
  the default curve. **Save calibration** validates the curve and adds it to the
  pending changes. The shade picker currently has no route back to the Options
  menu, so closing the dialog discards these edits.
  [Manual calibration save issue](https://github.com/sharwell/ha-crestron-home/issues/51)
- **Assisted calibration** lets you choose a visual group and accept the suggested
  midpoint of the largest remaining gap or enter your own target. Stage a move
  or use the shades' current positions. After aligning the shades, select
  **Record anchors** to add pending changes for shades that need a new or revised
  anchor. **Undo last** on the group selection screen reverses the last recorded
  changes in the current flow.

To apply assisted calibration, return to group selection, choose **Back**, and
select **Save changes** on the top-level Options menu. Staging can move shades
before any calibration is saved. The [Options flow diagram](docs/OPTIONS_FLOW.md)
shows the workflow branches.

## Troubleshooting

On the **Crestron Home** integration page, choose **Enable debug logging** from the
menu, reproduce the behavior, then disable debug logging to download the log.
To check batching, run a scene that sends several shade commands together and
look for the `POST /cws/api/shades/SetState` summary. Its `items` count and
`status` show how many targets were sent and how the controller responded.
Check the shade positions separately to confirm movement.
[Home Assistant debug logging instructions](https://www.home-assistant.io/docs/configuration/troubleshooting/#debug-logs-and-diagnostics)

Use **Download diagnostics** from the integration entry's menu to inspect learned
parameters, visual groups, recent stop plans and command batches, and assisted
calibration history. Before sharing diagnostics or logs, redact credentials,
controller addresses, private shade, room, and group names and IDs, and raw
request or response payloads. Check the whole file, including nested entries.

## Development setup

CI validates the integration with [hassfest](.github/workflows/hassfest.yml).
To run it locally, prepare a [Home Assistant Core checkout](https://github.com/home-assistant/core)
with its Python environment and hassfest dependencies in a sibling directory named `hass-core`.
From this repository's root, using Bash and the Core Python environment, run:

```bash
integration_path="$PWD/custom_components/crestron_home"
(cd ../hass-core && python3 -m script.hassfest --action validate --integration-path "$integration_path")
```

## License

This project is licensed under the terms of the MIT license. See [LICENSE](LICENSE) for details.
