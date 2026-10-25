"""scripts/move_site_subdomains.py: sites were given <slug>.genhaip.site (never registered); the script moves the stored
subdomain rows to the new base, skips a name that is already taken, and never touches custom domains."""
import os
import sys

from app.models.website import Site, SiteDomain
from tests.website_fixtures import make_tenant

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))
import move_site_subdomains as mover  # noqa: E402


def _site(db, slug):
    t = make_tenant(db, name=slug.capitalize())
    s = Site(tenant_id=t.id, name=slug, slug=slug, status="draft")
    db.add(s); db.flush()
    return t, s


def test_new_sites_get_the_new_base_and_old_rows_move(db):
    from app.core.config import settings
    assert settings.SITES_BASE_DOMAIN == "sites.genhaip.com"
    t, s = _site(db, "villa")
    old = SiteDomain(tenant_id=t.id, site_id=s.id, hostname="villa.genhaip.site", kind="subdomain", status="active", verify_token="t")
    custom = SiteDomain(tenant_id=t.id, site_id=s.id, hostname="www.villa.in", kind="custom", status="active", verify_token="t")
    t2, s2 = _site(db, "taken")
    clash_old = SiteDomain(tenant_id=t2.id, site_id=s2.id, hostname="taken.genhaip.site", kind="subdomain", status="active", verify_token="t")
    clash_new = SiteDomain(tenant_id=t2.id, site_id=s2.id, hostname="taken.sites.genhaip.com", kind="custom", status="removed", verify_token="t")
    db.add_all([old, custom, clash_old, clash_new]); db.commit()

    moves = mover.plan(db, "genhaip.site", "sites.genhaip.com")
    assert [(d.hostname, new) for d, new in moves] == [("villa.genhaip.site", "villa.sites.genhaip.com")]
    assert custom not in [d for d, _ in moves]
