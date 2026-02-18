# kubernetes-playground

This repo will serve as the DevOps course playground.

## Play 1

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update

helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx --create-namespace \
  --set controller.service.type=LoadBalancer

helm create devops1
```

Delete the following:

- `test` directory
- hpa.yaml
- serviceaccount.yaml
- httproute.yaml
- NOTES.txt

In the values.yaml file alter the port from 80 to 8080

Attempt to install the chart:

```bash
helm install devops1 .
```

Test:

```bash
kubectl get all -n default
```

You'll see nothing.

Debug...

You'll notice that since we deleted the servicesaccount.yaml file we have to mark in the values.yaml

```yaml
serviceAccount:
  # Specifies whether a service account should be created.
  create: false
```

Deploy again:

```bash
helm upgrade --install devops1 .
```

Test again:

```bash
kubectl get all -n default
```

You'll see things are created but pod fails.

Debug...

The default image that the chart is installing is nginx. Nginx by default works on port 80. Since we've altered the port value to 8080 in the values.yaml file we broke it. Change it back and rerun.

Deploy again:

```bash
helm upgrade --install devops1 .
```

Test again:

```bash
kubectl get all -n default
```

Everything works!!!
