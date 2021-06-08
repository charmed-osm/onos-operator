#!/usr/bin/env python3
# Copyright 2021 David Garcia
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""Charm the service.

Refer to the following post for a quick-start guide that will help you
develop a new k8s charm using the Operator Framework:

    https://discourse.charmhub.io/t/4208
"""

import logging
import requests


from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus
from ops.pebble import ServiceStatus

logger = logging.getLogger(__name__)

ASYNC_LOGGING = """
log4j.appender.async=org.apache.log4j.AsyncAppender
log4j.appender.async.appenders=rolling
"""

SYS_APP = "org.onosproject.drivers"
GUI_APP = "org.onosproject.gui2"


class OnosCharm(CharmBase):
    """Charm the service."""

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.onos_pebble_ready, self.add_onos_service_layer)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(
            self.on.list_activated_apps_action, self.list_activated_apps_action
        )
        self.framework.observe(
            self.on.list_available_apps_action, self.list_available_apps_action
        )
        self.framework.observe(self.on.activate_app_action, self.activate_app_action)
        self.framework.observe(
            self.on.deactivate_app_action, self.deactivate_app_action
        )
        self.framework.observe(self.on.restart_action, self.restart_action)

        self._stored.set_default(apps=set({SYS_APP}), started=False)

    @property
    def onos_container(self):
        return self.unit.get_container("onos")

    @property
    def onos_service(self):
        return self.onos_container.get_service("onos")

    @property
    def onos_apps(self) -> str:
        return ", ".join(self._stored.apps)

    def _on_config_changed(self, event):
        self._check_gui_app()

    def add_onos_service_layer(self, event):
        self._configure_async_logging()
        self.reload_onos_layer()
        self._restart_onos()
        self.unit.status = ActiveStatus()
        self.app.status = ActiveStatus()

    def reload_onos_layer(self):
        self.onos_container.add_layer(
            "onos",
            {
                "summary": "onos layer",
                "description": "pebble config layer for onos",
                "services": {
                    "onos": {
                        "override": "replace",
                        "summary": "onos service",
                        "command": "./bin/onos-service",
                        "startup": "enabled",
                        "environment": {
                            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                            "LANG": "en_US.UTF-8",
                            "LANGUAGE": "en_US:en",
                            "LC_ALL": "en_US.UTF-8",
                            "JAVA_HOME": "/usr/lib/jvm/zulu11-ca-amd64",
                            "JAVA_OPTS": self.config["java-opts"],
                            "ONOS_APPS": self.onos_apps,
                        },
                    }
                },
            },
            combine=True,
        )
        self._stored.started = True

    def activate_app_action(self, event):
        try:
            self._check_leadership()
            app_name = event.params["name"]
            self._check_app_exists(app_name)
            if app_name in self._stored.apps:
                raise Exception("application is already active")
            self._activate_app(app_name)
            event.set_results(
                {"output": f"application {app_name} successfully activated"}
            )
        except Exception as e:
            event.fail(f"Failed activating app {app_name}: {e}")

    def deactivate_app_action(self, event):
        try:
            self._check_leadership()
            app_name = event.params["name"]
            self._check_app_exists(app_name)
            if app_name not in self._stored.apps:
                raise Exception("application is not active")
            self._deactivate_app(app_name)
            event.set_results(
                {"output": f"application {app_name} successfully deactivated"}
            )
        except Exception as e:
            event.fail(f"Failed deactivating app {app_name}: {e}")

    def restart_action(self, event):
        try:
            self._restart_onos()
            event.set_results({"output": "service restarted"})
        except Exception as e:
            event.fail(f"Failed restarting onos: {e}")

    def list_activated_apps_action(self, event):
        try:
            event.set_results({"activated-apps": self.onos_apps})
        except Exception as e:
            event.fail(f"Failed listing active applications: {e}")

    def list_available_apps_action(self, event):
        try:
            apps = self._get_available_apps()
            event.set_results(
                {
                    "output": "successully retrieved list of all available apps",
                    "available-apps": ", ".join(apps),
                }
            )
        except Exception as e:
            event.fail(f"Failed listing available applications: {e}")

    def _get_available_apps(self):
        return [
            app_file_info.name
            for app_file_info in self.onos_container.list_files("/root/onos/apps/")
        ]

    def _activate_app(self, name):
        self._stored.apps.add(name)
        if self._stored.started:
            requests.post(
                f"http://localhost:8181/onos/v1/applications/{name}/active",
                auth=("onos", "rocks"),
            )

    def _deactivate_app(self, name):
        self._stored.apps.remove(name)
        if self._stored.started:
            requests.delete(
                f"http://localhost:8181/onos/v1/applications/{name}/active",
                auth=("onos", "rocks"),
            )

    def _restart_onos(self):
        container = self.unit.get_container("onos")
        if self.onos_service.current == ServiceStatus.ACTIVE:
            container.stop("onos")
        container.start("onos")

    def _configure_async_logging(self):
        files = self.onos_container.list_files("/root/onos/")
        apache_karaf_folder_name = None
        for file in files:
            if "apache-karaf" in file.name:
                apache_karaf_folder_name = file.name
                break
        if apache_karaf_folder_name:
            logging_content = self.onos_container.pull(
                f"/root/onos/{apache_karaf_folder_name}/etc/org.ops4j.pax.logging.cfg"
            ).read()
            if ASYNC_LOGGING not in logging_content:
                logging_content += ASYNC_LOGGING
                self.onos_container.push(
                    f"/root/onos/{apache_karaf_folder_name}/etc/org.ops4j.pax.logging.cfg",
                    logging_content,
                )

    def _check_app_exists(self, name):
        apps = self._get_available_apps()
        if name not in apps:
            raise Exception("Application does not exist.")

    def _check_leadership(self):
        if not self.unit.is_leader():
            raise Exception("this unit is not the leader")

    def _check_gui_app(self):
        gui_enabled = GUI_APP in self._stored.apps
        config_enable_gui = self.config.get("enable-gui")
        if config_enable_gui and not gui_enabled:
            self._activate_app(GUI_APP)
        elif not config_enable_gui and gui_enabled:
            self._deactivate_app(GUI_APP)



if __name__ == "__main__":
    main(OnosCharm)
