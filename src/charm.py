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


from charms.nginx_ingress_integrator.v0.ingress import IngressRequires
from jinja2 import Template
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus
from ops.pebble import ServiceStatus, FileType

logger = logging.getLogger(__name__)


WEB_PORT = 8181


ROOT_FOLDER = "/root/onos"


SYS_APP = "org.onosproject.drivers"
GUI_APP = "org.onosproject.gui2"


ALL_ROLES = [
    "group",
    "admin",
    "manager",
    "viewer",
    "systembundles",
    "ssh",
    "webconsole",
]

ADMIN_USERNAME = "admin"
ADMIN_GROUP_NAME = "admingroup"

GUEST_USERNAME = "guest"
GUEST_GROUP_NAME = "guestgroup"

DEFAULT_GROUPS = {
    ADMIN_GROUP_NAME: ALL_ROLES,
    GUEST_GROUP_NAME: ["group", "viewer"],
}

USERS_TEMPLATE = """
{% for user, userdata in users.items() %}{{user}} = {{userdata.password}},_g_:{{userdata.group}}
{% endfor %}

{% for group, roles in groups.items() %}_g_\:{{group}} = {{",".join(roles)}}
{% endfor %}
"""


ASYNC_LOGGING = """
log4j.appender.async=org.apache.log4j.AsyncAppender
log4j.appender.async.appenders=rolling
"""


class ConfigMissingException(Exception):
    pass


class OnosCharm(CharmBase):
    """Charm the service."""

    _stored = StoredState()
    _ingress = None

    def __init__(self, *args):
        super().__init__(*args)

        # Observe lifecycle events
        self.framework.observe(self.on.onos_pebble_ready, self._on_onos_pebble_ready)
        self.framework.observe(self.on.config_changed, self._on_config_changed)

        # Observe action events
        action_event_observer_mapping = {
            "restart": self._on_restart_action,
            "start": self._on_start_action,
            "stop": self._on_stop_action,
            "list_activated_apps": self._on_list_activated_apps_action,
            "list_available_apps": self._on_list_available_apps_action,
            "activate_app": self._on_activate_app_action,
            "deactivate_app": self._on_deactivate_app_action,
            "list_roles": self._on_list_roles_action,
            "add_user": self._on_add_user_action,
            "add_group": self._on_add_group_action,
            "delete_user": self._on_delete_user_action,
            "delete_group": self._on_delete_group_action,
        }
        for event, observer in action_event_observer_mapping.items():
            logger.debug(f"event: {event}")
            self.framework.observe(self.on[event].action, observer)

        self._stored.set_default(
            apps=set({SYS_APP}),
            started=False,
            ready=False,
            users=dict(),
            groups=dict(),
        )
        if "external-hostname" in self.config:
            self._ingress = IngressRequires(
                self,
                {
                    "service-hostname": self.config["external-hostname"],
                    "service-name": self.app.name,
                    "service-port": WEB_PORT,
                },
            )

    ##############################
    # PROPERTIES
    ##############################

    @property
    def onos_container(self):
        return self.unit.get_container("onos")

    @property
    def onos_service(self):
        return self.onos_container.get_service("onos")

    @property
    def onos_apps(self) -> str:
        return ", ".join(self._stored.apps)

    @property
    def pebble_started(self) -> bool:
        return self._stored.started

    @property
    def pebble_ready(self) -> bool:
        return self._stored.ready

    @property
    def users(self) -> dict:
        return self._stored.users

    @property
    def admin_user(self):
        return {
            ADMIN_USERNAME: {
                "group": ADMIN_GROUP_NAME,
                "password": self.config["admin-password"],
            }
        }

    @property
    def guest_user(self):
        return {
            GUEST_USERNAME: {
                "group": GUEST_GROUP_NAME,
                "password": self.config["guest-password"],
            }
        }

    @property
    def groups(self) -> dict:
        return self._stored.groups

    ##############################
    # LIFECYCLE OBSERVERS
    ##############################

    def _on_config_changed(self, event):
        """Observer for config-changed event"""
        try:
            self._configure()
            self.unit.status = ActiveStatus()
        except ConfigMissingException as e:
            self.unit.status = BlockedStatus(f"Config missing: {e}")
            event.defer()

    def _on_onos_pebble_ready(self, event):
        """Observer for onos-pebble-ready event"""
        try:
            self._stored.ready = True
            self._configure()
            self._add_onos_layer()
            self._restart_onos()
            self._stored.started = True
            self.unit.status = ActiveStatus()
            self.app.status = ActiveStatus()
        except ConfigMissingException as e:
            self.unit.status = BlockedStatus(f"Config missing: {e}")
            event.defer()

    ##############################
    # ACTION OBSERVERS
    ##############################

    def _on_list_activated_apps_action(self, event):
        """Observer for list-activated-apps action event"""
        try:
            event.set_results({"activated-apps": self.onos_apps})
        except Exception as e:
            event.fail(f"Failed listing active applications: {e}")

    def _on_list_available_apps_action(self, event):
        """Observer for list-available-apps action event"""
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

    def _on_activate_app_action(self, event):
        """Observer for activate-app action event"""
        try:
            app_name = event.params["name"]
            self._activate_app(app_name)
            event.set_results(
                {"output": f"application {app_name} successfully activated"}
            )
        except Exception as e:
            event.fail(f"Failed activating app: {e}")

    def _on_deactivate_app_action(self, event):
        """Observer for deactivate-app action event"""
        try:
            app_name = event.params["name"]
            self._deactivate_app(app_name)
            event.set_results(
                {"output": f"application {app_name} successfully deactivated"}
            )
        except Exception as e:
            event.fail(f"Failed deactivating app: {e}")

    def _on_restart_action(self, event):
        """Observer for restart action event"""
        try:
            self._restart_onos()
            event.set_results({"output": "service restarted"})
        except Exception as e:
            event.fail(f"Failed restarting onos: {e}")

    def _on_start_action(self, event):
        """Observer for start action event"""
        try:
            self._start_onos()
            event.set_results({"output": "service started"})
        except Exception as e:
            event.fail(f"Failed starting onos: {e}")

    def _on_stop_action(self, event):
        """Observer for stop action event"""
        try:
            self._stop_onos()
            event.set_results({"output": "service stopped"})
        except Exception as e:
            event.fail(f"Failed stopping onos: {e}")

    def _on_list_roles_action(self, event):
        """Observer for list-roles action event"""
        try:
            event.set_results({"roles": ", ".join(ALL_ROLES)})
        except Exception as e:
            event.fail(f"Failed listing the roles: {e}")

    def _on_add_user_action(self, event):
        """Observer for add-user action event"""
        try:
            username = event.params["username"]
            password = event.params["password"]
            group = event.params["group"]
            self._add_user(username, password, group)
            event.set_results({"output": f"user {username} added to group {group}"})
        except Exception as e:
            event.fail(f"Failed adding user: {e}")

    def _on_add_group_action(self, event):
        """Observer for add-group action event"""
        try:
            groupname = event.params["groupname"]
            roles = self._parse_roles(event.params["roles"])
            self._add_group(groupname, roles)
            event.set_results({"output": f"group {groupname} added with roles {roles}"})
        except Exception as e:
            event.fail(f"Failed adding group: {e}")

    def _on_delete_user_action(self, event):
        """Observer for delete-user action event"""
        try:
            username = event.params["username"]
            self._delete_user(username)
            event.set_results({"output": f"user {username} deleted"})
        except Exception as e:
            event.fail(f"Failed deleting user: {e}")

    def _on_delete_group_action(self, event):
        """Observer for delete-group action event"""
        try:
            groupname = event.params["groupname"]
            self._delete_group(groupname)
            event.set_results({"output": f"group {groupname} deleted"})
        except Exception as e:
            event.fail(f"Failed deleting group: {e}")

    ##############################
    # PEBBLE/SERVICES FUNCTIONS
    ##############################

    def _add_onos_layer(self):
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

    ##############################
    # CONFIGURATION
    ##############################

    def _configure(self):
        self._check_config()
        self._configure_gui_app()
        self._configure_users_and_groups()
        self._configure_ingress()
        self._configure_async_logging()

    def _configure_users_and_groups(self):
        apache_karaf_folder = self._get_apache_karaf_folder_path()
        if ADMIN_USERNAME not in self.users:
            self.users.update(self.admin_user)
        if self.config.get("enable-guest") and GUEST_USERNAME not in self.users:
            self.users.update(self.guest_user)
        if all(group not in self.groups for group in DEFAULT_GROUPS.keys()):
            self.groups.update(DEFAULT_GROUPS)
        if self.pebble_ready and apache_karaf_folder:
            t = Template(USERS_TEMPLATE)
            self.onos_container.push(
                f"{ROOT_FOLDER}/{apache_karaf_folder}/etc/users.properties",
                t.render(users=self.users, groups=self.groups),
            )

    def _configure_gui_app(self):
        gui_enabled = GUI_APP in self._stored.apps
        config_enable_gui = self.config.get("enable-gui")
        if config_enable_gui and not gui_enabled:
            self._activate_app(GUI_APP)
        elif not config_enable_gui and gui_enabled:
            self._deactivate_app(GUI_APP)

    def _configure_ingress(self):
        if self._ingress:
            self._ingress.update_config(
                {"service-hostname": self.config.get("external-hostname")}
            )

    def _configure_async_logging(self):
        apache_karaf_folder = self._get_apache_karaf_folder_path()
        if self.pebble_ready and apache_karaf_folder:
            logging_content = self.onos_container.pull(
                f"{ROOT_FOLDER}/{apache_karaf_folder}/etc/org.ops4j.pax.logging.cfg"
            ).read()
            if ASYNC_LOGGING not in logging_content:
                logging_content += ASYNC_LOGGING
                self.onos_container.push(
                    f"{ROOT_FOLDER}/{apache_karaf_folder}/etc/org.ops4j.pax.logging.cfg",
                    logging_content,
                )

    ##############################
    # ONOS OPERATIONS
    ##############################

    def _get_available_apps(self):
        return [
            app_file_info.name
            for app_file_info in self.onos_container.list_files(f"{ROOT_FOLDER}/apps")
        ]

    def _add_user(self, username, password, group):
        if group not in self.groups:
            raise Exception(f"group {group} does not exist")
        if username in self.users:
            raise Exception(f"user {username} already exists")
        if username in [ADMIN_USERNAME, GUEST_USERNAME]:
            raise Exception(f"username '{username}' is reserved")
        self.users.update({username: {"group": group, "password": password}})
        self._configure_users_and_groups()

    def _add_group(self, groupname, roles):
        if groupname in [ADMIN_GROUP_NAME, GUEST_GROUP_NAME]:
            raise Exception(f"groupname '{groupname}' is reserved")
        non_existing_roles = [role for role in roles if role not in ALL_ROLES]
        if non_existing_roles:
            raise Exception(f"role(s) {non_existing_roles} not exist")
        self.groups.update({groupname: roles})
        self._configure_users_and_groups()

    def _delete_user(self, username):
        if username not in self.users:
            raise Exception(f"user {username} does not exist")
        if username in [ADMIN_USERNAME, GUEST_USERNAME]:
            raise Exception(f"user {username} is reserved")
        self.users.pop(username)
        self._configure_users_and_groups()

    def _delete_group(self, groupname):
        if groupname in [ADMIN_GROUP_NAME, GUEST_GROUP_NAME]:
            raise Exception(f"groupname '{groupname}' is reserved")
        self.groups.pop(groupname)
        self._configure_users_and_groups()

    def _activate_app(self, name):
        self._check_app_exists(name)
        if name in self._stored.apps:
            raise Exception(f"application {name} is already active")
        self._stored.apps.add(name)
        if self.pebble_started:
            requests.post(
                f"http://localhost:8181/onos/v1/applications/{name}/active",
                auth=(ADMIN_USERNAME, self.config["admin-password"]),
            )

    def _deactivate_app(self, name):
        self._check_app_exists(name)
        if name not in self._stored.apps:
            raise Exception(f"application {name} is not active")
        self._stored.apps.remove(name)
        if self.pebble_started:
            requests.delete(
                f"http://localhost:8181/onos/v1/applications/{name}/active",
                auth=(ADMIN_USERNAME, self.config["admin-password"]),
            )

    def _restart_onos(self):
        container = self.unit.get_container("onos")
        if self.onos_service.current == ServiceStatus.ACTIVE:
            container.stop("onos")
        container.start("onos")

    def _start_onos(self):
        container = self.unit.get_container("onos")
        if self.onos_service.current == ServiceStatus.ACTIVE:
            raise Exception("onos service is already active")
        container.start("onos")

    def _stop_onos(self):
        container = self.unit.get_container("onos")
        if self.onos_service.current != ServiceStatus.ACTIVE:
            raise Exception("onos service is not running")
        container.stop("onos")

    ##############################
    # CHECK FUNCTIONS
    ##############################
    def _check_config(self):
        if "admin-password" not in self.config:
            raise ConfigMissingException(
                f"admin-password: juju config {self.app.name} admin-password=<pass>"
            )
        if self.config.get("enable-guest"):
            if "guest-password" not in self.config:
                raise ConfigMissingException(
                    f"guest-password: juju config {self.app.name} guest-password=<pass>"
                )

    def _check_app_exists(self, name):
        apps = self._get_available_apps()
        if name not in apps:
            raise Exception("Application does not exist.")

    ##############################
    # HELPER FUNCTIONS
    ##############################

    def _get_apache_karaf_folder_path(self):
        files = [
            file.name
            for file in self.onos_container.list_files(
                ROOT_FOLDER, pattern="apache-karaf-*"
            )
            if file.type == FileType.DIRECTORY
        ]
        return files[0]

    def _parse_roles(self, roles: str) -> list:
        """
        Parse roles

        :param: roles: Comma-listed roles without spaces

        :return: List of roles
        """
        if not roles or not isinstance(roles, str):
            raise ValueError("roles must be a string")
        role_list = roles.split(",")
        for role in role_list:
            if not role.isalnum():
                raise ValueError(f"role '{role}' is not alphanumeric")
        return role_list


if __name__ == "__main__":
    main(OnosCharm, use_juju_for_storage=True)
