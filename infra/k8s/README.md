# Kubernetes on Minikube

This folder contains the Kubernetes manifests for the ticketing system.

## Prerequisites

- `kubectl`
- `minikube`
- `docker`
- Local `.env` files for the services that provide secret values:
  - `services/auth/.env`
  - `services/database/.env`
  - `services/notification/.env`

Copy the example files first if needed:

```bash
cp services/auth/.env.example services/auth/.env
cp services/database/.env.example services/database/.env
cp services/notification/.env.example services/notification/.env
```

Then fill in the values.

## Create the Secret

The real secret file is not committed. Create it locally from the `.env` files, or create it manually from the template.

You have four options in `./scripts/run-minikube.sh`:

- enter the secret values manually
- read values from the service `.env` files
- copy an existing secret YAML file
- use the existing `infra/k8s/config/secret.yaml` already present in this repo

The template file is `infra/k8s/config/secret.example.yaml`. Do not apply that file to the cluster; it is only a guide.

If you want to generate the secret directly, run:

```bash
./scripts/create-k8s-secret.sh
```

## Run Everything Interactively

If you want one command to create secrets and deploy the stack, run:

```bash
./scripts/run-minikube.sh
```

The script will:

- create or reuse `infra/k8s/secret.yaml`
- start Minikube
- build the container images in Minikube's Docker daemon
- apply the Kubernetes manifests
- optionally apply the KEDA manifests
- optionally start a frontend port-forward

## Build the Images Manually

The deployment manifests use local image names such as `auth:latest`, `booking:latest`, and `frontend:latest`.

You can build them into Minikube's Docker daemon with:

```bash
eval $(minikube docker-env)
docker build -t auth:latest services/auth
docker build -t booking:latest services/booking
docker build -t booking-status:latest services/booking-status
docker build -t gateway:latest services/gateway
docker build -t notification:latest services/notification
docker build -t payment-mock:latest services/payment/mock
docker build -t frontend:latest frontend/vue
```

## Start Minikube

```bash
minikube start
kubectl config use-context minikube
```

## Apply the Manifests

Apply the real secret first, then the config map, then the workloads and services:

```bash
kubectl apply -f infra/k8s/secret.yaml
kubectl apply -f infra/k8s/configmap.yaml
kubectl apply -f infra/k8s/mysql-pvc.yaml
kubectl apply -f infra/k8s/services/
kubectl apply -f infra/k8s/deployments/
kubectl apply -f infra/k8s/keda/
```

## Verify the Deployment

```bash
kubectl get pods
kubectl get svc
kubectl get configmap ticketing-system-config
kubectl get secret ticketing-system-credentials
```

If you want to check logs for a service:

```bash
kubectl logs deploy/ticketing-system-auth
```

## Access the Frontend

The frontend service is `ClusterIP`, so access it with port forwarding:

```bash
kubectl port-forward svc/ticketing-system-frontend 30090:5173
```

Then open:

```bash
http://127.0.0.1:30090
```

## Access MySQL From a Local DB Client

The MySQL service is exposed as a `NodePort` so you can connect from a local database client.

Get the Minikube IP:

```bash
minikube ip
```

Then connect your DB client with:

- Host: Minikube IP
- Port: `30060`
- Database: `ticketing`
- User: `ticketuser`
- Password: `ticketpass`

If you prefer, you can also port-forward MySQL locally:

```bash
kubectl port-forward svc/ticketing-system-mysql 3306:3306
```

Then connect to `127.0.0.1:3306`.

## Notes

- `infra/k8s/secret.yaml` is ignored by git on purpose.
- `infra/k8s/secret.example.yaml` documents the required secret keys.
- `infra/k8s/configmap.yaml` contains non-secret configuration values.
- Do not run `kubectl apply -f infra/k8s/` on the whole folder because it would include `secret.example.yaml`.
- If a pod fails to start, check that the corresponding image exists in Minikube and that the secret/config map has been created.
