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

To limit how far a shade can close, set **Minimum position (%)** under
**Options → Calibrate a shade**, then apply it with **Save changes**. Close and
position commands below that limit target the minimum. Set it back to 0% to
allow full travel again. When assisted calibration skips an automatic move
below a shade's minimum, it also skips recording that shade's anchor.

### Stop and hold-to-move

**Predictive Stop** is enabled by default. It estimates where moving shades will
stop using learned travel speed, command latency, and deceleration. Stop is
best effort because the Crestron REST API lacks a native stop command.
If a shade is already below its configured minimum, Stop sends it to the
minimum. This can move the shade or reverse its direction.

If you turn off **Options → Predictive Stop**, Stop targets the latest known
position, subject to the minimum. It skips a shade when there is no known
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
Under **Assign shades**, choose a group beside each shade's name. If names
match, the shade IDs distinguish them. Use **Save changes** on the top-level
Options menu to apply the assignments.

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
  pending changes. Choose **Back to options** from the shade picker when you
  finish editing shades.
- **Assisted calibration** lets you choose a visual group and accept the suggested
  midpoint of the largest remaining gap or enter your own target. Stage a move
  or use the shades' current positions. After aligning the shades, select
  **Record anchors** to add pending changes for shades that need a new or revised
  anchor. **Undo last** on the group selection screen reverses the last recorded
  changes in the current flow.

For assisted calibration, return to group selection and choose **Back**. Select
**Save changes** on the top-level Options menu to apply either type of
calibration. Staging can move shades before any calibration is saved.
The [Options flow diagram](docs/OPTIONS_FLOW.md) shows the workflow branches.

## Troubleshooting

On the **Crestron Home** integration page, choose **Enable debug logging** and
reproduce the behavior. In Home Assistant 2026.11 or later, select **Show logs**
and then **Download** to save the integration's live log.
**Disable debug logging** can download the full Home Assistant log, which may
include messages from other integrations.

To check batching, run a scene that sends several shade commands together and
look for the `POST /cws/api/shades/SetState` summary. Its
`items` count and `status` describe the batch and the controller's response.
Check the shade positions separately to confirm movement. Shade and group
aliases let you follow related messages from the same integration run.
Review the relevant log excerpt and remove any private details before sharing.
[Home Assistant debug logging instructions](https://www.home-assistant.io/docs/configuration/troubleshooting/#debug-logs-and-diagnostics)

Use **Download diagnostics** from the integration entry's menu to inspect learned
parameters, visual groups, recent stop plans and command batches, and assisted
calibration history. The Crestron section uses fresh shade and group aliases
for each download and reports event times in seconds relative to the download.
When reporting an issue, copy the top-level `data` section into the report or
into a new file with a generic filename. Home Assistant adds its own metadata
around that section and can include the config entry ID in the original filename.

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
