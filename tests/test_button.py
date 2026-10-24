"""Tests for the per-dog automation buttons."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import Context

from custom_components.dogassistant.button import CARE_BUTTONS, DogCareButton, async_setup_entry


@pytest.mark.parametrize(('key', 'service', 'payload', 'icon'), CARE_BUTTONS)
async def test_press_routes_to_dog_and_preserves_context(key, service, payload, icon):
    button = DogCareButton(None, 'subentry', 'rover', None, key=f'button_{key}', service=service, payload=payload)
    button.hass = SimpleNamespace(services=SimpleNamespace(async_call=AsyncMock()))
    context = Context(user_id='caregiver')
    button._context = context

    await button.async_press()

    button.hass.services.async_call.assert_awaited_once_with(
        'dogassistant', service, {'dog_id': 'rover', **payload}, blocking=True, context=context,
    )


async def test_setup_creates_separate_buttons_for_each_dog():
    entry = SimpleNamespace(
        subentries={key: SimpleNamespace(unique_id=key, subentry_id=key) for key in ('rover', 'fido')},
        runtime_data=SimpleNamespace(manager=SimpleNamespace(data={'dogs': {'rover': {}, 'fido': {}}})),
    )
    batches = []

    def add(entities, **kwargs):
        batches.append((entities, kwargs))

    await async_setup_entry(None, entry, add)

    assert len(batches) == 2
    assert len({entity.unique_id for entities, _ in batches for entity in entities}) == 16
    for entities, kwargs in batches:
        assert len(entities) == 8
        assert all(entity.dog_id == kwargs['config_subentry_id'] for entity in entities)
        assert all(entity.entity_description.translation_key for entity in entities)
