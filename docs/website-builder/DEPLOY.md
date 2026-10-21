# Deploying the website builder

Order matters; each step is safe on its own (the module is off until an owner switches it on).

1. **Backend.** Pull, rebuild `api worker beat frontend`. Migration 158 runs with the others (idempotent).
2. **Renderer.** `docker compose -f docker-compose.prod.yml up -d --build sites` (listens on 127.0.0.1:3020).
   Set `SITES_REVALIDATE_SECRET` (any long random string) in the compose environment and the same value in
   `backend/.env`, plus `SITES_RENDERER_URL=http://haip_sites:3020`.
3. **Site domain.** Buy the site domain (e.g. `genhaip.site`), set `SITES_BASE_DOMAIN` in `backend/.env`. DNS:
   `*.genhaip.site` and `sites.genhaip.site` → the VPS (or Cloudflare proxied). `SITES_CNAME_TARGET=sites.genhaip.site`.
4. **nginx (host).** A wildcard certificate for `*.genhaip.site` (certbot DNS challenge or Cloudflare origin cert), then:

   ```nginx
   server {
     listen 443 ssl; server_name *.genhaip.site;
     ssl_certificate /etc/ssl/genhaip.site/fullchain.pem; ssl_certificate_key /etc/ssl/genhaip.site/privkey.pem;
     location / {
       proxy_pass http://127.0.0.1:3020;
       proxy_set_header Host $host;
       proxy_set_header X-Forwarded-Host $host;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto https;
     }
   }
   ```
5. **Custom domains.** Recommended: Cloudflare for SaaS on the site domain's zone (fallback origin
   `sites.genhaip.site`), then set `CLOUDFLARE_API_TOKEN` (Zone › SSL and Certificates › Edit) and
   `CLOUDFLARE_ZONE_ID`. HAIP registers each verified domain; Cloudflare issues its certificate and proxies to nginx,
   which needs a `server_name _` block with the same `proxy_pass` for unknown hosts. Without Cloudflare, issue a
   certificate per verified domain with certbot and add it to that default block.
6. **Razorpay.** Each property connects its own Razorpay account (Settings › Payments). The existing webhook URL
   receives website payments too; enable the `payment_link.paid` event (already required for booking links).
   Razorpay activation needs the Contact and Policies pages live first.
7. **Switch on.** Owner: Marketing › Website › Switch on → Create my website → edit → Publish.
