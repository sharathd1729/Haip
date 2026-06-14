# Dograh Voice AI — Infrastructure Setup Guide

**Platform**: Dograh (self-hosted) + Sarvam AI (STT/TTS) + Claude (LLM)
**Purpose**: AI-powered multilingual voice agent for HAIP hospitality clients
**Runs in parallel** with CallerDesk and Acefone — do not replace existing IVR.

---

## 1. Oracle Cloud Free Tier VM

### 1.1 Sign Up

1. Go to [cloud.oracle.com](https://cloud.oracle.com) and create a free account.
2. Select **India (ap-mumbai-1)** as home region for lowest latency.
3. Verify identity with credit card (not charged for Always Free resources).

### 1.2 Create ARM VM (Always Free — 24 GB RAM)

1. Console → Compute → Instances → **Create Instance**
2. Name: `haip-dograh-01`
3. Image: **Ubuntu 22.04 (aarch64)**
4. Shape: **VM.Standard.A1.Flex** → OCPUs: 4, Memory: 24 GB (Always Free limit)
5. Networking: Create new VCN or use existing. Enable **Assign public IPv4 address**.
6. SSH Keys: Upload your public key or paste it.
7. Click **Create**.

### 1.3 Open Firewall Ports

In Oracle Console → Networking → Virtual Cloud Networks → your VCN → Security Lists → Default:

Add Ingress Rules:

| Port | Protocol | Source CIDR | Notes |
|------|----------|-------------|-------|
| 22   | TCP | 0.0.0.0/0 | SSH |
| 80   | TCP | 0.0.0.0/0 | HTTP (Let's Encrypt challenge) |
| 443  | TCP | 0.0.0.0/0 | HTTPS |
| 3010 | TCP | 0.0.0.0/0 | Dograh dashboard |
| 5060 | UDP | 0.0.0.0/0 | SIP signaling |

Also open OS-level firewall on the VM:

```bash
sudo iptables -I INPUT -p tcp --dport 3010 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
sudo iptables -I INPUT -p udp --dport 5060 -j ACCEPT
sudo netfilter-persistent save
```

### 1.4 SSH Access

```bash
ssh ubuntu@<your-vm-public-ip>
```

---

## 2. Docker + Docker Compose

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y docker.io
sudo apt install -y docker-compose-plugin
sudo usermod -aG docker $USER

# Re-login to apply group change
newgrp docker

# Verify
docker --version
docker compose version
```

---

## 3. Deploy Dograh

```bash
# Fetch official docker-compose
curl -o docker-compose.yaml \
  https://raw.githubusercontent.com/dograh-hq/dograh/main/docker-compose.yaml

# Start Dograh (disable telemetry)
REGISTRY=ghcr.io/dograh-hq ENABLE_TELEMETRY=false \
  docker compose up -d --pull always
```

### 3.1 Verify Dograh Running

```bash
curl http://localhost:3010/health
# Expected: {"status": "ok"}
```

Open dashboard: `http://<your-vm-public-ip>:3010`

---

## 4. Twilio Free Trial (Dev/Testing)

> For production, replace with VoIP.ms or Plivo (cheaper per-minute rates in India).

1. Sign up at [twilio.com](https://twilio.com) — no credit card required for trial.
2. Get **$15 free credits** (~1,000 minutes of inbound/outbound).
3. Buy a phone number: Console → Phone Numbers → Buy a Number (free with trial).
4. Configure inbound webhook:
   - Phone Numbers → Manage → Active Numbers → click your number
   - Voice & Fax → A Call Comes In → Webhook
   - URL: `https://<your-dograh-server>/telephony/inbound`
   - Method: HTTP POST

---

## 5. Sarvam AI Configuration in Dograh

> Sarvam AI provides best-in-class STT/TTS for Hindi, Kannada, Tamil, and code-switched Hinglish.

1. Open Dograh dashboard → **Settings → Voice Providers**
2. **Add STT Provider:**
   - Provider: `Custom`
   - Endpoint: `https://api.sarvam.ai/speech-to-text`
   - API Key: `[SARVAM_API_KEY]`
   - Model: `saarika:v2`
   - Language: `hi-IN` (default; enable auto-detect)
3. **Add TTS Provider:**
   - Provider: `Custom`
   - Endpoint: `https://api.sarvam.ai/text-to-speech`
   - API Key: `[SARVAM_API_KEY]`
   - Model: `bulbul:v1`
   - Language: `hi-IN`

Get API key: [dashboard.sarvam.ai](https://dashboard.sarvam.ai)

---

## 6. Claude API Configuration in Dograh

1. Open Dograh dashboard → **Settings → LLM Providers**
2. **Add Anthropic Claude:**
   - Provider: `Anthropic`
   - API Key: `[ANTHROPIC_API_KEY]`
   - Model: `claude-sonnet-4-6`
   - Max tokens: `500` (keep responses short for voice)
   - Temperature: `0.3` (deterministic responses)

Get API key: [console.anthropic.com](https://console.anthropic.com)

---

## 7. Environment Variables

Generate a webhook secret:

```bash
openssl rand -hex 32
```

Variables needed (add to HAIP backend `.env`):

```env
# Dograh Voice AI
DOGRAH_WEBHOOK_SECRET=REPLACE_ME_GENERATE_WITH_OPENSSL
DOGRAH_SERVER_URL=https://your-dograh-server.com
DOGRAH_AGENT_ID_DEFAULT=

# SIP / Telephony (Twilio for dev, VoIP.ms for production)
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_PHONE_NUMBER=
```

> **Security**: Each tenant gets their own `dograh_webhook_secret` stored encrypted in the tenants table.
> The `DOGRAH_WEBHOOK_SECRET` env var is a global fallback only — never used if per-tenant secret is set.

---

## 8. DNS + TLS (Production)

```bash
# Install Caddy (auto-HTTPS)
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install caddy

# /etc/caddy/Caddyfile
sudo tee /etc/caddy/Caddyfile <<EOF
voice.your-domain.com {
    reverse_proxy localhost:3010
}
EOF

sudo systemctl reload caddy
```

Point `voice.your-domain.com` DNS A record to your Oracle VM IP.

---

## 9. Health Check

```bash
# Dograh health
curl https://voice.your-domain.com/health

# Test webhook (replace with real values)
curl -X POST https://your-haip-server.com/api/v1/webhooks/dograh/ratha \
  -H "Content-Type: application/json" \
  -H "x-dograh-signature: <hmac>" \
  -d '{"event": "call.completed", ...}'
```
