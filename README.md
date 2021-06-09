# ONOS operator

## Description

Charm the deploys ONOS, that stands for Open Network Operating System.

ONOS provides the control plane for a software-defined network (SDN), managing network components, such as switches and links, and running software programs or modules to provide communication services to end hosts and neighboring networks.

## Prepare local environment

Requirements:

- vCPU: 2
- Memory: 4G
- Disk: 20G

> With multipass: `multipass launch -c 2 -m 4G -d 20G`

Install Microk8s:

```bash
sudo snap install microk8s --classic --channel 1.20/stable
sudo usermod -a -G microk8s `whoami`
sudo chown -f -R `whoami` ~/.kube
newgrp microk8s
microk8s.status --wait-ready
microk8s.enable storage ingress dns
```

Install, deploy, and configure Juju:

```bash
sudo snap install juju --classic --channel 2.9/stable
juju bootstrap microk8s
juju add-model onos
```

## Usage

### Deploy the charm (locally)

Clone the repository:

```bash
git clone https://github.com/charmed-osm/onos-operator
cd onos-operator/
```

Build and deploy the charm:

```bash
sudo snap install charmcraft
charmcraft build
juju deploy ./onos.charm --resource onos-image=onosproject/onos:latest
```

Set admin-password:

```bash
juju config onos admin-password=myadminpass
```

### Exposing the UI

The current way of exposing the service is using the `nginx-ingress-integrator` charm. It can be easily configured executing the following commands:

```bash
K8S_WORKER_IP=192.168.0.12  # change this IP with the IP of your K8s worker
juju config onos external-hostname=onos.$K8S_WORKER_IP.nip.io

juju deploy nginx-ingress-integrator ingress
juju relate ingress onos
```

### Configuration options

Enable/disable the GUI:

```bash
juju config onos enable-gui=true  # or false
```

Set JAVA_OPTS:

```bash
juju config onos java-opts=...
```

Set password for admin user:

```bash
juju config onos admin-password=myadminpass
```

Enable/disable guest user:

```bash
juju config onos enable-guest=true
```

Set password for guest user:

```bash
juju config onos guest-password=myadminpass
```

### Actions

#### Service lifecycle

Restart ONOS service:

```bash
juju run-action onos/0 restart --wait
```

Start ONOS service:

```bash
juju run-action onos/0 start --wait
```

Stop ONOS service:

```bash
juju run-action onos/0 stop --wait
```

#### Application management

List activated application:

```bash
juju run-action onos/0 list-activated-apps --wait
```

List all available applications:

```bash
juju run-action onos/0 list-available-apps --wait
```

Activate an application:

```bash
juju run-action onos/0 activate-app --string-args name=org.onosproject.acl --wait
```

Deactivate an application:

```bash
juju run-action onos/0 deactivate-app --string-args name=org.onosproject.acl --wait
```

#### Authenticatìon: users, groups and roles

List roles:

```bash
juju run-action onos/0 list-roles --wait
```

Add user:

```bash
juju run-action onos/0 add-user --string-args username=myuser password=mypass group=admingroup --wait
```

Add group:

```bash
juju run-action onos/0 add-group --string-args groupname=mygroup roles=group,admin,manager,viewer --wait
```

Delete user:

```bash
juju run-action onos/0 delete-user --string-args username=myuser --wait
```

Delete group:

```bash
juju run-action onos/0 delete-group --string-args groupname=mygroup --wait
```

## Developing

Create and activate a virtualenv with the development requirements:

    virtualenv -p python3 venv
    source venv/bin/activate
    pip install -r requirements-dev.txt

<!-- ## Testing

The Python operator framework includes a very nice harness for testing
operator behaviour without full deployment. Just `run_tests`:

    ./run_tests -->
