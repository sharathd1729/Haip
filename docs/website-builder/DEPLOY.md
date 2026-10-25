# Deploying the website builder

Order matters; each step is safe on its own (the module is off until an owner switches it on).

1. **Backend.** Pull, rebuild `api worker beat frontend`. Migration 158 runs with the others (idempotent).
2. **Renderer.** `docker compose -f docker-compose.prod.yml up -d --build sites` (listens on 127.0.0.1:3020).
   Set `SITES_REVALIDATE_SECRET` (any long random string) in the compose environment and the same value in
   `backend/.env`, plus `SITES_RENDERER_URL=http://haip_sites:3020`.
3. **Site domain.** Sites live at `<slug>.sites.genhaip.com` (the default `SITES_BASE_DOMAIN`; `genhaip.site` was never
   registered). DNS (Cloudflare, **DNS only / grey cloud**: Cloudflare's free certificate does not cover a second-level
   wildcard): `*.sites.genhaip.com` and `sites.genhaip.com` → A record to the VPS IP. If `backend/.env` still sets
   `SITES_BASE_DOMAIN=genhaip.site` or `SITES_CNAME_TARGET=sites.genhaip.site`, delete those lines. Move sites created
   on the old name: `docker compose -f docker-compose.prod.yml exec api python3 scripts/move_site_subdomains.py`
   (dry run), then add `--apply`.
4. **nginx (host).** A Let's Encrypt wildcard certificate by DNS challenge (needs a Cloudflare API token with
   Zone › DNS › Edit for genhaip.com, stored in `/root/.secrets/cloudflare.ini` as `dns_cloudflare_api_token = ...`,
   `chmod 600`):

   ```bash
   apt-get install -y python3-certbot-dns-cloudflare
   certbot certonly --dns-cloudflare --dns-cloudflare-credentials /root/.secrets/cloudflare.ini      -d 'sites.genhaip.com' -d '*.sites.genhaip.com'
   ```

   then `/etc/nginx/conf.d/haip-sites.conf`:

   ```nginx
   server {
     listen 80; server_name sites.genhaip.com *.sites.genhaip.com;
     return 301 https://$host$request_uri;
   }
   server {
     listen 443 ssl; server_name sites.genhaip.com *.sites.genhaip.com;
     ssl_certificate /etc/letsencrypt/live/sites.genhaip.com/fullchain.pem;
     ssl_certificate_key /etc/letsencrypt/live/sites.genhaip.com/privkey.pem;
     location / {
       proxy_pass http://127.0.0.1:3020;
       proxy_set_header Host $host;
       proxy_set_header X-Forwarded-Host $host;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto https;
     }
   }
   ```
   `nginx -t && systemctl reload nginx`. certbot renews it on its own (same DNS challenge).
5. **Custom domains.** Recommended: Cloudflare for SaaS on the site domain's zone (fallback origin
   `sites.genhaip.com`), then set `CLOUDFLARE_API_TOKEN` (Zone › SSL and Certificates › Edit) and
   `CLOUDFLARE_ZONE_ID`. HAIP registers each verified domain; Cloudflare issues its certificate and proxies to nginx,
   which needs a `server_name _` block with the same `proxy_pass` for unknown hosts. Without Cloudflare, issue a
   certificate per verified domain with certbot and add it to that default block.
6. **Razorpay.** Each property connects its own Razorpay account (Settings › Payments). The existing webhook URL
   receives website payments too; enable the `payment_link.paid` event (already required for booking links).
   Razorpay activation needs the Contact and Policies pages live first.
7. **Switch on.** Owner: Marketing › Website › Switch on → Create my website → edit → Publish.
