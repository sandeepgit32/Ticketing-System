# ticketing-system Helm chart

This chart deploys the full ticketing system microservices stack:
- mysql
- redis
- auth
- booking
- booking-status
- payment-mock
- notification
- gateway
- frontend
- optional KEDA scaling

## Quickstart

```bash
cd infra/helm/ticketing-system
helm lint .
helm install ticketing-system . \
  --set secrets.jwtSecret="your_jwt_secret" \
  --set secrets.mysqlRootPassword="your_mysql_root_pass" \
  --set secrets.mysqlPassword="your_mysql_pass" \
  --set secrets.defaultAdminPassword="your_admin_pass"
```

## Notes
- `gateway` & `frontend` are NodePort by default at 30080 and 30090.
- For production, configure external ingress/LoadBalancer and replace values.
- `keda.enabled` toggles queue-driven autoscaling.

## Cleanup

```bash
helm uninstall ticketing-system
```
