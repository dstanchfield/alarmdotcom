"""Interfaces with Alarm.com alarm control panels."""
from __future__ import annotations

import logging
import re
from enum import Enum

from homeassistant import core
from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    CodeFormat,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    STATE_ALARM_ARMED_AWAY,
    STATE_ALARM_ARMED_HOME,
    STATE_ALARM_ARMED_NIGHT,
    STATE_ALARM_ARMING,
    STATE_ALARM_DISARMED,
    STATE_ALARM_DISARMING,
)
from homeassistant.core import callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback, DiscoveryInfoType
from pyalarmdotcomajax.devices.partition import Partition as libPartition
from pyalarmdotcomajax.exceptions import NotAuthorized

from .base_device import HardwareBaseDevice
from .const import (
    CONF_ARM_AWAY,
    CONF_ARM_CODE,
    CONF_ARM_HOME,
    CONF_ARM_NIGHT,
    CONF_FORCE_BYPASS,
    CONF_NO_ENTRY_DELAY,
    CONF_SILENT_ARM,
    DATA_CONTROLLER,
    DOMAIN,
)
from .controller import AlarmIntegrationController

log = logging.getLogger(__name__)


async def async_setup_entry(
    hass: core.HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,  # pylint: disable=unused-argument
) -> None:
    """Set up the sensor platform and create a master device."""

    controller: AlarmIntegrationController = hass.data[DOMAIN][config_entry.entry_id][DATA_CONTROLLER]

    async_add_entities(
        AlarmControlPanel(
            controller=controller,
            device=device,
        )
        for device in controller.api.devices.partitions.values()
    )


class AlarmControlPanel(HardwareBaseDevice, AlarmControlPanelEntity):  # type: ignore
    """Alarm.com Alarm Control Panel entity."""

    device_type_name: str = "Alarm Control Panel"
    _device: libPartition

    def __init__(
        self,
        controller: AlarmIntegrationController,
        device: libPartition,
    ) -> None:
        """Pass coordinator to CoordinatorEntity."""

        super().__init__(controller, device, device.system_id)

        self._attr_code_format = (
            (
                CodeFormat.NUMBER
                if (isinstance(arm_code, str) and re.search("^\\d+$", arm_code))
                else CodeFormat.TEXT
            )
            if (arm_code := controller.options.get(CONF_ARM_CODE))
            else None
        )

        self._attr_supported_features = (
            AlarmControlPanelEntityFeature.ARM_HOME | AlarmControlPanelEntityFeature.ARM_AWAY
        )

        if self._device.supports_night_arming:
            self._attr_supported_features |= AlarmControlPanelEntityFeature.ARM_NIGHT

    @callback
    def _update_device_data(self) -> None:
        """Update the entity when coordinator is updated."""

        self._attr_state = self._determine_state(self._device.state)

        self._attr_extra_state_attributes.update({"uncleared_issues": str(self._device.uncleared_issues)})

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Send disarm command."""
        if self._validate_code(code):
            self._attr_state = STATE_ALARM_DISARMING

            try:
                await self._device.async_disarm()
            except NotAuthorized:
                self._show_permission_error("disarm")

    async def async_alarm_arm_night(self, code: str | None = None) -> None:
        """Send arm night command."""

        arm_options = self._controller.options.get(CONF_ARM_NIGHT, {})

        if self._validate_code(code):
            self._attr_state = STATE_ALARM_ARMING

            try:
                await self._device.async_arm_night(
                    force_bypass=CONF_FORCE_BYPASS in arm_options,
                    no_entry_delay=CONF_NO_ENTRY_DELAY in arm_options,
                    silent_arming=CONF_SILENT_ARM in arm_options,
                )
            except NotAuthorized:
                self._show_permission_error("arm_night")

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        """Send arm home command."""

        arm_options = self._controller.options.get(CONF_ARM_HOME, {})

        if self._validate_code(code):
            self._attr_state = STATE_ALARM_ARMING

            try:
                await self._device.async_arm_stay(
                    force_bypass=CONF_FORCE_BYPASS in arm_options,
                    no_entry_delay=CONF_NO_ENTRY_DELAY in arm_options,
                    silent_arming=CONF_SILENT_ARM in arm_options,
                )
            except NotAuthorized:
                self._show_permission_error("arm_home")

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Send arm away command."""

        arm_options = self._controller.options.get(CONF_ARM_AWAY, {})

        if self._validate_code(code):
            self._attr_state = STATE_ALARM_ARMING

            try:
                await self._device.async_arm_away(
                    force_bypass=CONF_FORCE_BYPASS in arm_options,
                    no_entry_delay=CONF_NO_ENTRY_DELAY in arm_options,
                    silent_arming=CONF_SILENT_ARM in arm_options,
                )
            except NotAuthorized:
                self._show_permission_error("arm_away")

    #
    # Helpers
    #

    def _determine_state(self, state: Enum | None) -> str | None:
        """Return the state of the device."""

        log.info("Processing state %s for %s", state, self.name or self._device.name)

        if self._device.malfunction or not state:
            return None

        match state:
            case libPartition.DeviceState.DISARMED:
                return str(STATE_ALARM_DISARMED)
            case libPartition.DeviceState.ARMED_STAY:
                return str(STATE_ALARM_ARMED_HOME)
            case libPartition.DeviceState.ARMED_AWAY:
                return str(STATE_ALARM_ARMED_AWAY)
            case libPartition.DeviceState.ARMED_NIGHT:
                return str(STATE_ALARM_ARMED_NIGHT)
            case _:
                log.error(f"Cannot determine state. Found raw state of {state}.")
                return None

    def _validate_code(self, code: str | None) -> bool | str:
        """Validate given code."""
        check: bool | str = (arm_code := self._controller.options.get(CONF_ARM_CODE)) in [
            None,
            "",
        ] or code == arm_code
        if not check:
            log.warning("Wrong code entered.")
        return check
