# Putting Ego Labs online (Windows machine + Cloudflare Tunnel)

This runs Ego Labs on a Windows computer at home or in the office and makes it reachable at your own domain
with HTTPS, for you and your team. A **Cloudflare Tunnel** connects the computer to Cloudflare from the
inside, so there's nothing to set up on your router, no ports to open, and it works without a fixed IP.

```
browser ──https──▶ Cloudflare ──tunnel──▶ cloudflared (on your PC) ──▶ web app   (app.example.com)
                                                                    └─▶ storage  (files.example.com)
```

The database, Redis, storage and API are not reachable from outside; only the web app and storage (for
uploading and downloading videos with signed, expiring links) go through the tunnel.

**You need:** the Windows PC with Docker Desktop (8 GB+ RAM, 50 GB+ free disk), a domain, a free Cloudflare
account, and the Google sign-in client you already made. Plan about an hour the first time.

Replace `example.com` below with your domain. Two addresses are used, both one level below your domain
(Cloudflare's free certificate covers exactly one level):

| Setting | Example | What it is |
| --- | --- | --- |
| `APP_DOMAIN` | `app.example.com` | where people open Ego Labs |
| `FILES_DOMAIN` | `files.example.com` | where videos are uploaded to and downloaded from |

---

## 1. Get a domain on Cloudflare

1. Create a free account at <https://dash.cloudflare.com/sign-up>.
2. **Domain Registration → Register Domains**, search for a name and buy it (about $10–15 a year, at cost).
   It's then already on Cloudflare, nothing else to do.
   *Already have a domain elsewhere?* Use **Add a domain** instead and change its nameservers at your
   registrar to the two Cloudflare shows you; wait until Cloudflare says the domain is **Active**.

## 2. Create the tunnel

1. In the Cloudflare dashboard open **Zero Trust** (first time: pick a team name and the **Free** plan).
2. **Networks → Tunnels → Create a tunnel → Cloudflared**. Name it `ego-labs` and save.
3. Under **Install and run connectors** choose **Docker**. You'll see a command with
   `--token eyJ...`: copy only the long token after `--token` (starts with `eyJ`). Don't run the command;
   Ego Labs starts the connector itself.
4. Click **Next** to add the **public hostnames** (you can add the second one afterwards with
   **Public Hostname → Add a public hostname**):

   | Subdomain | Domain | Service type | URL |
   | --- | --- | --- | --- |
   | `app` | `example.com` | `HTTP` | `web:3000` |
   | `files` | `example.com` | `HTTP` | `minio:9000` |

5. For the **files** hostname open **Additional application settings → HTTP Settings** and set
   **HTTP Host Header** to `files.example.com`. (Upload and download links are signed for that name.)
6. Save the tunnel.

Recommended: in the main dashboard for your domain, **Caching → Cache Rules → Create rule**, name it
"No cache for files", *Hostname equals* `files.example.com`, action **Bypass cache**, deploy. Your videos then
never sit in Cloudflare's cache.

## 3. Let Google sign-in work on your domain

In Google Cloud Console → **APIs & Services → Credentials** → your OAuth client:

1. Under **Authorised redirect URIs** add `https://app.example.com/auth/google/callback` (keep the
   localhost one if you still use Ego Labs locally). Save.
2. **OAuth consent screen / Audience**: add your team's Google accounts as test users, or **Publish app**
   so any Google account can sign in.

## 4. Prepare the PC

1. **Docker Desktop → Settings → General:** tick **Start Docker Desktop when you sign in to your computer**.
2. **Windows power settings:** Settings → System → Power → *Screen and sleep*: set **"When plugged in, put my
   device to sleep after" = Never**. (The screen may turn off; the PC must not sleep.)
3. Windows must be signed in for Docker Desktop to run: after a restart (e.g. Windows Update), sign in and
   Ego Labs comes back by itself. To make even that automatic, turn on automatic sign-in for this PC
   (`netplwiz` on Windows 10/11 Pro), only if the PC is somewhere safe.
4. Give Docker enough memory: create `C:\Users\<you>\.wslconfig` with
   ```
   [wsl2]
   memory=6GB
   ```
   then run `wsl --shutdown` in PowerShell and restart Docker Desktop. (By default WSL gets half your RAM,
   which is tight for video processing on an 8 GB machine.)

## 5. Fill in `.env`

In PowerShell, in the project folder:

```powershell
cd "D:\path\to\egolab"
git pull
.\scripts\deploy.ps1 -NewSecrets
```

That prints three random secrets. Open `.env` (`notepad .env`) and set:

```
# paste the three lines printed above, replacing the old ones
JWT_SECRET=...
POSTGRES_PASSWORD=...
MINIO_ROOT_PASSWORD=...

APP_DOMAIN=app.example.com
FILES_DOMAIN=files.example.com
CLOUDFLARE_TUNNEL_TOKEN=eyJ...

GOOGLE_CLIENT_ID=...apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-...
PASSWORD_LOGIN=false

# the admins' Google accounts, separated by commas (one is fine)
OWNER_EMAIL=you@gmail.com,partner@gmail.com
```

Write the domains without `https://`. Keep this file private: it holds every password.

> **Already ran Ego Labs on this PC with the default passwords?** The database keeps the password it was
> created with, so new passwords won't match it. If the data is only test data, start fresh (this **deletes**
> the local videos and results): `docker compose down -v`. To keep the data, keep the old
> `POSTGRES_PASSWORD` and `MINIO_ROOT_PASSWORD` values for now and ask for help changing them.

If PowerShell refuses to run scripts ("running scripts is disabled"), allow local scripts once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## 6. Start it

```powershell
.\scripts\deploy.ps1
```

It checks `.env` (and tells you exactly what to fix), gets the latest code, builds, and starts everything
including the tunnel. The first build takes 10–20 minutes. When it prints **"Ego Labs is running"**:

1. Open `https://app.example.com` → **Sign in** → **Continue with Google** with an `OWNER_EMAIL` account:
   you are an admin. Anyone else who signs in sees "Waiting for access" until you give them a role in
   **Settings → Users**. Set your limits in **Settings → Limits**; big uploads and long videos then wait for
   you in **Settings → Requests**.
2. In the tunnel page on Cloudflare the connector shows **Healthy**.
3. Upload a short video (Data → Upload) and watch it process.

## Everyday use

| To | Run (in the project folder) |
| --- | --- |
| Update to the latest version | `.\scripts\deploy.ps1` |
| See what's running | `docker compose ps` |
| Read the logs | `docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail 100 api worker web cloudflared` |
| Stop it | `docker compose -f docker-compose.yml -f docker-compose.prod.yml stop` |
| Start it again | `.\scripts\deploy.ps1 -NoPull` |
| Back up | `.\scripts\backup.ps1` |

Everything restarts on its own after a crash or a reboot (once Docker Desktop is running).

## Backups

`.\scripts\backup.ps1` saves the database and every stored file into `backups\<date>_<time>\`
(`database.dump` and `files.tgz`). Copy that folder to another disk or cloud storage; a backup on the same
disk won't survive the disk failing. Run it weekly, or daily when you're adding a lot of video
(Windows **Task Scheduler** can run it for you: action `powershell.exe`, arguments
`-ExecutionPolicy Bypass -File "D:\path\to\egolab\scripts\backup.ps1"`, start in the project folder).

**Restoring** a backup (replace `2026-09-25_0643` with the backup's folder name):

```powershell
docker compose stop api worker scheduler web
# database
docker compose exec -T postgres dropdb -U egolabs egolabs
docker compose exec -T postgres createdb -U egolabs egolabs
docker compose cp backups\2026-09-25_0643\database.dump postgres:/tmp/restore.dump
docker compose exec -T postgres pg_restore -U egolabs -d egolabs --no-owner /tmp/restore.dump
# stored files
docker compose stop minio
docker run --rm -v egolabs_minio-data:/data -v "${PWD}\backups\2026-09-25_0643:/backup" alpine sh -c "rm -rf /data/* /data/.[!.]* ; tar xzf /backup/files.tgz -C /data"
.\scripts\deploy.ps1 -NoPull
```

## If something's wrong

| What you see | What to do |
| --- | --- |
| `deploy.ps1` lists problems | Fix those lines in `.env` and run it again. |
| The site shows a Cloudflare error (502 / 1033) | The PC is off, asleep, or the stack is stopped. Check `docker compose ps` and the tunnel status on Cloudflare. |
| Google says `redirect_uri_mismatch` | The redirect URI in Google must be exactly `https://app.example.com/auth/google/callback`. |
| You signed in but see "Waiting for access", or aren't admin | Your Google email isn't exactly in `OWNER_EMAIL` in `.env` (comma-separated). Fix it and run `.\scripts\deploy.ps1 -NoPull`; you're admin on your next click. |
| The login page says Google sign-in isn't set up | `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` are empty in `.env`; fill them in and run `.\scripts\deploy.ps1 -NoPull`. |
| Uploads fail, or videos don't play | Check the `files` hostname in the tunnel (service `minio:9000`, HTTP Host Header `files.example.com`) and that `FILES_DOMAIN` in `.env` matches it. |
| The API won't start, logs say `JWT_SECRET must be set` | `JWT_SECRET` is missing or too short: run `.\scripts\deploy.ps1 -NewSecrets` and paste the new value. |
| The API logs `password authentication failed` | The database was created with other passwords; see the note in step 5. |
| Uploads are much slower than your connection | The tunnel uses HTTP/2 by default, which is fastest on most home connections. Check it with `docker compose -f docker-compose.yml -f docker-compose.prod.yml logs cloudflared \| Select-String protocol` (it should say `http2`). Uploading from the PC that runs Ego Labs sends every byte out and back in again, so it is slower than from another computer. |
| Processing is very slow or containers restart | Not enough memory: raise `memory` in `.wslconfig` (step 4) or process fewer videos at once. |

**Bandwidth:** everything people upload and download goes through your home or office internet connection;
the upload speed of that connection is what limits how fast teammates can send videos.
