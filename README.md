# ONOS operator

## Description

Charm the deploys ONOS, that stands for Open Network Operating System.

ONOS provides the control plane for a software-defined network (SDN), managing network components, such as switches and links, and running software programs or modules to provide communication services to end hosts and neighboring networks.

## Usage

### Deploy the charm (locally)

Clone the repository:

```bash
git clone https://github.com/charmed-osm/onos-operator
cd onos-operator/
```

Build and deploy the charm:

```bash
charmcraft build
juju deploy ./onos.charm --resource onos-image=onosproject/onos:latest
```

### Configuration options

#### Enable/disable the GUI:

```bash
juju config onos enable-gui=true  # or false
```

#### Set JAVA_OPTS:

```bash
juju config onos java-opts=...
```

### Actions

#### Restart ONOS service

```bash
juju run-action onos/0 restart
```

#### List activated application

```bash
juju run-action onos/0 list-activated-apps --wait
```

#### List all available applications

```bash
juju run-action onos/0 list-available-apps --wait
```

#### Activate an application

```bash
juju run-action onos/0 activate-app --string-args name=org.onosproject.acl --wait
```

#### Deactivate an application

```bash
juju run-action onos/0 deactivate-app --string-args name=org.onosproject.acl --wait
```

### Exposing the UI

The current way of exposing the service is using the `nginx-ingress-integrator` charm. It can be easily configured executing the following commands:

```bash
K8S_WORKER_IP=192.168.0.12  # change this IP with the IP of your K8s worker
juju config onos external-hostname=onos.$K8S_WORKER_IP.nip.io

juju deploy nginx-ingress-integrator ingress
juju relate ingress onos
```

## Developing

Create and activate a virtualenv with the development requirements:

    virtualenv -p python3 venv
    source venv/bin/activate
    pip install -r requirements-dev.txt

## Testing

The Python operator framework includes a very nice harness for testing
operator behaviour without full deployment. Just `run_tests`:

    ./run_tests
