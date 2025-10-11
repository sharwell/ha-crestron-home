# Options flow overview

Use this diagram to see how Crestron Home's Options menu branches into calibration editors and
where anchors are actually persisted. The emphasis is on preventing accidental exits from the
Assisted calibration wizard or per-shade editor before anchors are saved.

## Combined diagram

<div role="img" aria-label="Options flow highlighting calibration commit points and no-save exits">

```mermaid
flowchart TD
    entry([HA Settings → Devices & Services → Crestron Home → Configure → Options])
    options[[Options]]

    entry --> options
    options --> openEditor
    options --> selectGroup
    options --> visual[Visual groups]
    options --> predictive[Predictive Stop (on/off)]
    options --> reset[Reset learned parameters]
    options --> invert[Global invert default]

    subgraph ShadeEditor["Calibrate a shade — per-shade editor"]
        direction TB
        openEditor[[Open shade editor]]
        actions[Insert anchor\nRemove anchor\nReset to defaults\nInvert axis (per shade)]
        validate{{Validate anchors:\n0% and 100% endpoints\nNon-decreasing raw values}}
        save[[Save — Saves]]
        cancel[Cancel/Back — Does not save]
        saved[(Curve saved)]
        unsaved[(No anchors saved)]

        openEditor --> actions
        actions --> validate
        validate -->|Pass| save
        validate -->|Fail| actions
        save --> saved
        actions --> cancel
        cancel --> unsaved
    end

    subgraph AssistedWizard["Assisted calibration — group-scoped wizard"]
        direction TB
        selectGroup[[Select visual group]]
        pickTarget[Pick target\n(largest-gap suggested)]
        stage[[Stage (batched move)]]
        align[Visually align by eye]
        record[[Done/Record anchors\n(per shade, skip unchanged) — Saves]]
        undo[Undo last (optional)]
        exitSaved[(Exit wizard — Saves)]
        exitUnsaved[(No anchors saved)]

        selectGroup --> pickTarget
        pickTarget --> stage
        stage --> align
        align --> record
        record --> exitSaved
        record --> undo
        undo --> align
        align -. Navigate away / Cancel before Done/Record .-> exitUnsaved
    end
```

</div>

### Legend

- **Rounded rectangles** mark user actions.
- **Double-bordered rectangles** label commit points that save anchors.
- **Plain rectangles** identify navigation or context-only branches.
- **Parallelograms** highlight the persistent outcomes after each branch.
- **Diamonds** represent validation checks.
- Dashed arrows call out exits that do **not** persist changes.

## Per-shade editor flow

1. Open **Options → Calibrate a shade**.
2. Adjust anchors as needed: insert, remove, reset to defaults, or toggle the per-shade **Invert axis**.
3. **Save** commits the calibrated curve after it passes the monotonicity and endpoint validation.
4. Choosing **Cancel/Back** or navigating away exits without saving; no anchors are persisted.

## Assisted calibration flow

1. Launch **Options → Assisted calibration**.
2. Select a visual group, then pick a target percentage (the wizard suggests the largest remaining gap).
3. Stage the batched move, visually align the windows, and use **Done/Record anchors** to store new points
   for each shade that actually changed (unchanged shades are skipped automatically).
4. Optionally undo the last recording step to retry alignment.
5. Leaving the wizard or cancelling **before Done/Record** means **No anchors saved**.
