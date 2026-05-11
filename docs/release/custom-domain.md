# Custom Domain Runbook

Target hostname: `azwatch.operator.lat`

## Goal

Serve the public alpha dashboard from a neutral Operator.lat subdomain while
keeping the Azure Static Web Apps default hostname available as a fallback.

## DNS Records

The `azwatch` host must point to Azure Static Web Apps. In the DNS provider for
`operator.lat`, remove any existing `A` or `AAAA` records for `azwatch`, then add:

| Type | Name | Value |
| --- | --- | --- |
| CNAME | `azwatch` | `gray-island-09dc9e703.7.azurestaticapps.net` |

If using staged TXT validation, Azure CLI provides a validation token with:

```powershell
az staticwebapp hostname show `
  --name <static-web-app-name> `
  --resource-group <resource-group> `
  --hostname azwatch.operator.lat `
  --query "validationToken" `
  --output tsv
```

For staged TXT validation, add the token only in the DNS provider:

| Type | Name | Value |
| --- | --- | --- |
| TXT | `_dnsauth.azwatch` | Azure CLI validation token |

Some DNS providers want the fully qualified name
`_dnsauth.azwatch.operator.lat` instead of `_dnsauth.azwatch`.

If the parent domain has CAA records, allow Azure's managed certificate issuer.
Azure App Service managed certificates are issued by DigiCert, so add this CAA
record alongside any existing CAA records. In Vercel's DNS UI, use the apex name
`@` and put the full CAA content in the value field:

| Type | Name | Value | TTL |
| --- | --- | --- | --- |
| CAA | `@` | `0 issue "digicert.com"` | `60` |

Without this record, Azure can validate DNS routing but fail when issuing the
managed TLS certificate.

Do not commit validation tokens or Azure resource identifiers to this repository.

## Azure Binding

After DNS is visible, complete or refresh the binding:

```powershell
az staticwebapp hostname set `
  --name <static-web-app-name> `
  --resource-group <resource-group> `
  --hostname azwatch.operator.lat `
  --validation-method cname-delegation
```

## Verification

```powershell
Resolve-DnsName azwatch.operator.lat -Type CNAME
Invoke-WebRequest -Uri https://azwatch.operator.lat/ -Method Head -UseBasicParsing
Invoke-WebRequest -Uri https://azwatch.operator.lat/api/latest.json -Method Head -UseBasicParsing
```

Expected checks:

- DNS resolves to the Static Web Apps default hostname.
- HTTPS certificate is issued and trusted.
- Dashboard returns `200`.
- `/api/latest.json` returns `200` with public CORS headers.