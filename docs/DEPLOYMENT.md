# Deployment

The model this describes: **you host one deployment**, and each client
organization gets its own campaign with its own links. Staff open a link on
their own phone or laptop and answer. Nobody installs anything, and you do not
configure a device per employee.

---

## Configuration

| Variable | Required | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | always | Report generation. Reports fail without it. |
| `CYBERFEEDBACK_ADMIN_TOKEN` | when not on loopback | **Operator** role — full control. |
| `CYBERFEEDBACK_PUBLIC_URL` | when not on loopback | Public base URL used to build campaign links. |
| `CYBERFEEDBACK_HOST` / `_PORT` | no | Bind address, default `127.0.0.1:8080`. |
| `CYBERFEEDBACK_THREADS` | no | Worker threads, default 16. |
| `OPENAI_MODEL` | no | Default `gpt-5.5`. |
| `OPENAI_TIMEOUT_SECONDS` | no | Default 120. |
| `OPENAI_MAX_RETRIES` | no | Default 3. |

Generate the operator token with real entropy:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

`serve.py` refuses to start if a non-loopback bind is missing an admin token or
a public URL, because both failures surface as a broken product in front of a
client rather than as an error you see.

---

## Run it

### Local development

```powershell
$env:OPENAI_API_KEY="sk-..."
python src/serve.py
```

Loopback only, no tokens needed — the admin gate trusts loopback when no admin
token is set. `python src/server.py` also still works, but that is Flask's
development server and must never face a client.

### Docker

```bash
docker build -t cyberfeedback .

docker run -d --name cyberfeedback \
  -p 127.0.0.1:8080:8080 \
  -v cyberfeedback-data:/app/src/data \
  -v cyberfeedback-reports:/app/src/Generated_PDF_Report \
  -e OPENAI_API_KEY="sk-..." \
  -e CYBERFEEDBACK_ADMIN_TOKEN="..." \
  -e CYBERFEEDBACK_PUBLIC_URL="https://assess.example.com" \
  cyberfeedback
```

Publishing to `127.0.0.1:8080` rather than `0.0.0.0:8080` is deliberate: the
container is reached only through the reverse proxy below, so the app is never
directly exposed.

The two volumes hold everything a client cares about. They are what you back up
and what you delete on request.

---

## HTTPS

Assessment answers must not travel in clear text. Terminate TLS at a reverse
proxy in front of the container — this is not optional before inviting a client.

Caddy, which obtains and renews certificates automatically:

```
assess.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

nginx equivalent:

```nginx
server {
    listen 443 ssl;
    server_name assess.example.com;

    ssl_certificate     /etc/letsencrypt/live/assess.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/assess.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Set `CYBERFEEDBACK_PUBLIC_URL` to the `https://` address. Behind a proxy the
request-derived host is frequently wrong, and a wrong link is indistinguishable
from a broken product to the person who receives it.

---

## Encryption at rest

The application does not encrypt what it writes; it relies on the host's
full-disk encryption. Enable it before the first client, and be able to say so
plainly when asked — [DATA_HANDLING.md](DATA_HANDLING.md) tells clients to ask.

## Backups

The Docker volumes above are the whole state. Back them up on a schedule, and
encrypt the backups — an unencrypted backup silently undoes the disk-encryption
answer you just gave the client.

```bash
docker run --rm \
  -v cyberfeedback-data:/data:ro \
  -v "$PWD":/backup \
  alpine tar czf /backup/cyberfeedback-data-$(date +%F).tar.gz -C /data .
```

## Deleting a client's data

```bash
docker exec -it cyberfeedback python scripts/delete_org_data.py --list
docker exec -it cyberfeedback python scripts/delete_org_data.py --org acme-ltd
```

Irreversible, and it prints what it will remove before asking you to retype the
slug. Remember the backups above hold copies — delete those too, or your written
confirmation of deletion is not true.

---

## Not yet built

Be aware of these before scaling past a handful of clients:

- **Report generation is synchronous.** A request occupies a worker thread for
  the whole OpenAI call. 16 threads absorbs a normal session; a very large
  simultaneous batch would queue. Moving generation to a background worker is the
  next change if you outgrow it.
- **Storage is JSON files**, with a single registry file. Fine for the current
  scale, and the documented threshold for revisiting it is in
  [ROADMAP.md](ROADMAP.md) Phase 0.
- **One operator token for all clients.** Leadership credentials are scoped per
  campaign, but yours is global. Rotating it means re-entering it everywhere;
  there is no second operator account.
