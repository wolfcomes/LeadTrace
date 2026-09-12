# LeadTrace Internal TLS

Production Nginx expects these two deployment-managed files in this directory:

```text
leadtrace.crt  Server certificate followed by any intermediate CA certificates
leadtrace.key  Unencrypted server private key, readable only by the Nginx service
```

Do not commit either file. The repository ignores `*.crt`, `*.key`, `*.pem`,
and certificate request artifacts below this directory.

Use the organization's internal CA. The certificate Subject Alternative Name
must include the exact LAN DNS name used by operators and, only when clients
connect by a fixed address, the assigned LAN IP address. A self-signed leaf
certificate is not an accepted production configuration.

Issue the certificate under the internal CA's server-auth policy, copy it to
the deployment host through the approved secret channel, set the key mode to
`0600`, and restart Nginx only after `nginx -t` succeeds. Install the internal
CA root in every managed client trust store before cutover. Do not bypass
browser certificate warnings.

The external `${LEADTRACE_PORT}` maps to Nginx's TLS listener at container port
8080. PostgreSQL, Redis, FastAPI, metrics, and frontend development ports stay
on internal networks and must not be published to the LAN.

Before production cutover verify:

```bash
openssl s_client -connect leadtrace.lan:8876 -servername leadtrace.lan \
  -verify_return_error </dev/null
curl --fail --cacert /path/to/internal-ca.crt https://leadtrace.lan:8876/health/live
```

Record certificate serial number, SANs, issuer, `notBefore`, `notAfter`, and
the renewal owner in the change record. Alert at least 30 days before expiry.
