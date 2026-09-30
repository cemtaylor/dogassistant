# Dog Assistant

Dog Assistant is a local-first Home Assistant custom integration for tracking daily dog care, health records, schedules, documents, and the all-important answer to “has someone already fed the dog?”

## Features

- One Home Assistant device and dashboard card per dog.
- Meals, walks, toilet events, medication doses, weight, and categorized notes.
- Medication schedules, vaccination history, appointments, insurance, registration, vet, and emergency information.
- Automatic caregiver attribution from the Home Assistant user.
- Private PDF/image uploads and portable ZIP exports.
- Native sensors, binary sensors, calendar, image entity, and automation actions.
- Everything is stored locally in the Home Assistant configuration and retained until you delete it.

Dog Assistant targets Home Assistant 2026.8 or newer.

## Installation

### HACS custom repository

1. Open HACS, choose **Integrations**, then open the menu and choose **Custom repositories**.
2. Add this repository URL with category **Integration**.
3. Install **Dog Assistant** and restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration**, search for **Dog Assistant**, and complete setup.
5. Open the Dog Assistant integration and use **Add entry** to create each dog.

### Manual installation

Copy `custom_components/dogassistant` into the `custom_components` directory in your Home Assistant configuration, then restart Home Assistant.

## Add the card

The integration serves its bundled card at `/dogassistant/dogassistant-card.js`.

1. Open **Settings → Dashboards → Resources**. If Resources is hidden, enable Advanced mode in your Home Assistant user profile.
2. Add `/dogassistant/dogassistant-card.js?v=0.2.8` as a **JavaScript module**.
3. Edit a dashboard, add a card, and choose **Dog Assistant**.
4. Select the dog in the graphical card editor.

Equivalent YAML:

```yaml
type: custom:dogassistant-card
dog: DOG_ID_SELECTED_BY_THE_EDITOR
```

## Actions

All actions accept a Dog Assistant device target in the automation editor. They also accept `dog_id` for programmatic calls.

- `dogassistant.log_meal`
- `dogassistant.log_treat`
- `dogassistant.start_walk`
- `dogassistant.end_walk`
- `dogassistant.log_walk`
- `dogassistant.log_toilet`
- `dogassistant.record_medication`
- `dogassistant.log_weight`
- `dogassistant.add_note`

Example NFC-tag automation:

```yaml
actions:
  - action: dogassistant.log_meal
    data:
      dog_id: YOUR_DOG_ID
      meal_type: dinner
      food: Normal food
      amount: 250
      unit: g
```

## Reminder blueprint

Import [`blueprints/automation/dogassistant_attention.yaml`](blueprints/automation/dogassistant_attention.yaml) using its raw GitHub URL. It triggers when a selected Dog Assistant attention sensor turns on and runs a notification action sequence that you provide.

## Private data and backups

Structured records live in Home Assistant's `.storage` data and uploaded documents live under `.storage/dogassistant/documents`. Document routes require Home Assistant authentication. Files are not separately encrypted, so protect Home Assistant host access and backups appropriately.

Authenticated non-admin household users can view the care overview and timeline and log daily care. Home Assistant administrator rights are required to edit profiles and structured records, delete history, upload or delete documents, and export the complete dataset. Non-admin card responses omit documents, appointments, vaccinations, and sensitive profile fields.

To keep resource use bounded, Dog Assistant retains at most 50,000 care events per household and automatically drops the oldest event when that limit is exceeded. Document storage is limited to 200 files and 50 MiB in total, with a 10 MiB limit per file. Export before reaching the event limit if you need a permanent external archive.

The card's **Export this dog** button downloads JSON, CSV, and uploaded documents in one ZIP. There is currently no import operation.

Home Assistant Recorder stores the integration's entity history separately and applies Home Assistant's normal Recorder retention settings. Dog Assistant deliberately keeps detailed notes and document metadata out of entity state attributes.

## Removal

Remove Dog Assistant from **Settings → Devices & services** and uninstall it from HACS. Home Assistant does not automatically erase private stored records or documents during uninstall; remove `.storage/dogassistant.data` and `.storage/dogassistant/` only after making any export you need and stopping Home Assistant.

## Development

The repository includes a Podman Compose setup for local testing:

```bash
podman compose up -d
```

Home Assistant is then available at <http://localhost:8123>. The local custom component is mounted read-only into the container.
