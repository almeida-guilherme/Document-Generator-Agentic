# Putting Pidi on AWS Lightsail

One small server runs everything with Docker: the app (`Dockerfile`) and Caddy in front of it for HTTPS (`compose.yaml`, `deploy/Caddyfile`). All data (database, recordings, documents, the secret key) is in one Docker volume on the server's disk, which Lightsail snapshots back up.

You need: an AWS account, a domain (or a subdomain of one you have) and your OpenAI key. About 30 minutes.

## 1. Create the server

In the [Lightsail console](https://lightsail.aws.amazon.com/):

1. **Create instance**. Region: the one closest to you (e.g. São Paulo, `sa-east-1`). Platform **Linux/Unix**, blueprint **OS Only → Ubuntu 24.04 LTS**.
2. Plan: **2 GB RAM** (enough for one user and long recordings). Name it `pidi`. Create.
3. **Networking** tab of the instance:
   - **Create static IP** and attach it to `pidi` (otherwise the IP changes when the server restarts).
   - **IPv4 Firewall**: add a rule for **HTTPS (443)**. HTTP (80) and SSH (22) are there already; Caddy needs 80 to get the certificate. Optionally limit SSH to your own IP.

## 2. Point the domain at it

At your domain's DNS (Lightsail **Domains & DNS**, Route 53 or your registrar), add an **A record**: `pidi.yourdomain.com` → the static IP. It can take a few minutes to work; `ping pidi.yourdomain.com` should show the static IP.

## 3. Install Docker

Open the server's terminal (**Connect using SSH** in the console, or `ssh ubuntu@<static IP>` with the key Lightsail gives you), then:

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker ubuntu        # use docker without sudo
exit                                  # log out and connect again for that to apply
```

A swap file avoids running out of memory while the image is built:

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 4. Get the app and configure it

```bash
git clone https://github.com/almeida-guilherme/Document-Generator-Agentic.git pidi
cd pidi
cp deploy/env.example .env
nano .env        # set PDD_DOMAIN and OPENAI_API_KEY; save with Ctrl+O, Enter, Ctrl+X
chmod 600 .env
```

## 5. Start it

```bash
docker compose up -d --build     # the first build takes a few minutes
docker compose logs -f caddy     # wait for "certificate obtained successfully", then Ctrl+C
```

Create your account (sign-up is closed in `.env`, so this is the only way in):

```bash
docker compose exec app python -m web.create_user you@example.com
```

Open `https://pidi.yourdomain.com` and log in.

## 6. Backups

Instance → **Snapshots** → turn on **Automatic snapshots** (daily, the last 7 kept). A snapshot holds the whole disk, including the data volume. To restore, create a new instance from a snapshot and attach the static IP to it.

## Everyday tasks

| Task | Command (in `~/pidi` on the server) |
|---|---|
| Update to the latest version | `git pull && docker compose up -d --build` |
| See what the app is doing | `docker compose logs -f app` |
| Reset a password | `docker compose exec app python -m web.create_user you@example.com` |
| Restart | `docker compose restart` |
| Disk space used by recordings | `docker system df -v \| grep pidi-data` |

## Costs and limits

- The 2 GB Lightsail plan is a fixed monthly price (check the current price and disk size in the console). A 40-minute project takes about 550 MB of disk (the recording, about 250 MB, plus its screenshots and audio), so a 60 GB disk holds roughly 90 of them. Deleting a project frees its space.
- OpenAI usage is separate: about $0.40 for a 5-minute recording, about $2 for 40 minutes. Set a monthly budget limit in the OpenAI dashboard.
- One project is processed at a time. See `requirement.md` for what to add before more people use it.
