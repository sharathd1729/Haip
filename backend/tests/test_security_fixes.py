"""
Tests for critical security and performance audit fixes.

Covers:
  SEC-2  — Messages endpoint filters by tenant_id (conversation isolation)
  SEC-3  — Celery workers call set_tenant_context before querying
  PERF-1 — Analytics _p95_seconds uses SQL percentile_cont (no Python sort)
  PERF-2 — Instagram DM task uses JSONB containment query (no table scan)
  PERF-3 — reports.fetch_team uses aggregate query (no per-user N+1)
  PERF-4 — leads_service.get_leads_pipeline batches property-interest lookup (no per-inquiry N+1)
"""

import inspect
import ast
import textwrap
import pytest
from unittest.mock import MagicMock, patch, call
from sqlalchemy.orm import Session


# ──────────────────────────────────────────────────────────────────────────────
# SEC-2: Conversation messages endpoint filters by tenant_id
# ──────────────────────────────────────────────────────────────────────────────

class TestConversationMessagesTenantFilter:
    def test_messages_query_filters_tenant_id(self):
        """
        GET /conversations/{id}/messages must include tenant_id in the query
        to prevent cross-tenant message exposure.
        """
        import app.api.v1.endpoints.conversations as conv_module
        source = inspect.getsource(conv_module.get_messages)
        # The query must use tenant_id in the filter
        assert "tenant_id" in source, (
            "get_messages must filter messages by tenant_id, not just conversation_id"
        )

    def test_messages_filter_uses_current_user_tenant(self):
        """The tenant_id filter must come from the authenticated user, not the request body."""
        import app.api.v1.endpoints.conversations as conv_module
        source = inspect.getsource(conv_module.get_messages)
        # Must reference current_user.tenant_id
        assert "current_user.tenant_id" in source, (
            "messages query must use current_user.tenant_id, not a path/query param"
        )


# ──────────────────────────────────────────────────────────────────────────────
# SEC-3: Celery workers call set_tenant_context before querying
# ──────────────────────────────────────────────────────────────────────────────

class TestWorkerTenantContext:
    """
    Verify each critical worker imports and calls set_tenant_context
    before performing any tenant-scoped DB queries.
    """

    def _get_worker_source(self, module_path: str) -> str:
        import importlib
        mod = importlib.import_module(module_path)
        return inspect.getsource(mod)

    def _assert_set_tenant_context_called(self, module_path: str, task_fn_name: str):
        import importlib
        mod = importlib.import_module(module_path)
        fn = getattr(mod, task_fn_name, None)
        if fn is None:
            # Some tasks use nested functions
            source = inspect.getsource(mod)
        else:
            source = inspect.getsource(fn)
        assert "set_tenant_context" in source, (
            f"{module_path}.{task_fn_name} must call set_tenant_context() "
            "before querying tenant-scoped tables"
        )

    def test_whatsapp_task_sets_context(self):
        source = self._get_worker_source("app.workers.tasks.whatsapp")
        assert "set_tenant_context" in source

    def test_call_ingest_sets_context(self):
        source = self._get_worker_source("app.workers.tasks.call_ingest")
        assert "set_tenant_context" in source

    def test_ai_scoring_sets_context(self):
        source = self._get_worker_source("app.workers.tasks.ai_scoring")
        assert "set_tenant_context" in source

    def test_transcription_sets_context(self):
        source = self._get_worker_source("app.workers.tasks.transcription")
        assert "set_tenant_context" in source

    def test_concierge_draft_sets_context(self):
        source = self._get_worker_source("app.workers.tasks.concierge_draft")
        assert "set_tenant_context" in source

    def test_send_whatsapp_sets_context(self):
        source = self._get_worker_source("app.workers.tasks.send_whatsapp")
        assert "set_tenant_context" in source

    def test_classify_sets_context(self):
        source = self._get_worker_source("app.workers.tasks.classify")
        assert "set_tenant_context" in source

    def test_judge_sets_context(self):
        source = self._get_worker_source("app.workers.tasks.judge")
        assert "set_tenant_context" in source

    def test_wrap_up_sets_context(self):
        source = self._get_worker_source("app.workers.tasks.wrap_up")
        assert "set_tenant_context" in source

    def test_owner_digest_sets_context(self):
        source = self._get_worker_source("app.workers.tasks.owner_digest")
        assert "set_tenant_context" in source

    def test_lost_reason_cluster_sets_context(self):
        source = self._get_worker_source("app.workers.tasks.lost_reason_cluster")
        assert "set_tenant_context" in source

    def test_dpdp_purge_sets_context(self):
        source = self._get_worker_source("app.workers.tasks.dpdp_purge")
        assert "set_tenant_context" in source

    def test_instagram_dm_sets_context(self):
        source = self._get_worker_source("app.workers.tasks.process_instagram_dm")
        assert "set_tenant_context" in source

    def test_send_instagram_dm_sets_context(self):
        source = self._get_worker_source("app.workers.tasks.send_instagram_dm")
        assert "set_tenant_context" in source


# ──────────────────────────────────────────────────────────────────────────────
# PERF-1: Analytics p95 must use SQL percentile_cont, not Python sort
# ──────────────────────────────────────────────────────────────────────────────

class TestAnalyticsP95:
    """
    _p95_seconds previously computed percentile_cont(0.95) over
    Call.duration_seconds directly (call LENGTH, not response latency) --
    a real bug, since the name/docstring/OwnerDailyStats field all say
    "response time." It now delegates to the same shared
    message_metrics.chat_response_p95_seconds() the dashboard widget uses,
    so both agree under the "response time" label. These tests check the
    delegation and the shared function's own SQL, not ORM-query internals
    that no longer apply now that it's a single source of truth.
    """

    def test_p95_delegates_to_shared_chat_metric(self):
        """_p95_seconds must reuse message_metrics.chat_response_p95_seconds, not recompute its own metric."""
        import app.api.v1.endpoints.analytics as analytics_module
        source = inspect.getsource(analytics_module._p95_seconds)
        assert "return chat_response_p95_seconds(" in source, (
            "_p95_seconds must delegate to message_metrics.chat_response_p95_seconds "
            "so it agrees with the ResponseTimeWidget instead of measuring call duration"
        )

    def test_shared_metric_does_not_load_all_rows(self):
        """chat_response_p95_seconds must not load all message gaps into Python."""
        import app.services.message_metrics as message_metrics_module
        source = inspect.getsource(message_metrics_module.chat_response_p95_seconds)
        assert "sorted(" not in source
        assert ".all()" not in source

    def test_shared_metric_uses_percentile_cont_within_group(self):
        """chat_response_p95_seconds must use PostgreSQL percentile_cont/within group syntax."""
        import app.services.message_metrics as message_metrics_module
        source = inspect.getsource(message_metrics_module.chat_response_p95_seconds)
        assert "percentile_cont" in source
        assert "WITHIN GROUP" in source

    def test_p95_returns_float_on_empty(self):
        """_p95_seconds must return 0.0 (not raise) when there are no matching messages."""
        from app.api.v1.endpoints.analytics import _p95_seconds
        from datetime import datetime, timezone, timedelta
        db = MagicMock()
        db.execute.return_value.scalar.return_value = None
        result = _p95_seconds(db, "tid", datetime.now(timezone.utc) - timedelta(days=7), datetime.now(timezone.utc))
        assert result == 0.0

    def test_p95_returns_float_on_result(self):
        """_p95_seconds must return the scalar result as a float."""
        from app.api.v1.endpoints.analytics import _p95_seconds
        from datetime import datetime, timezone, timedelta
        db = MagicMock()
        # Simulate PostgreSQL returning 123.5 from percentile_cont
        db.execute.return_value.scalar.return_value = 123.5
        result = _p95_seconds(db, "tid", datetime.now(timezone.utc) - timedelta(days=7), datetime.now(timezone.utc))
        assert result == 123.5

    def test_p95_forwards_property_ids_filter(self):
        """_p95_seconds must forward property_ids so the property-filtered KPI drill-down still works."""
        from app.api.v1.endpoints.analytics import _p95_seconds
        from datetime import datetime, timezone, timedelta
        db = MagicMock()
        db.execute.return_value.scalar.return_value = 42.0
        start = datetime.now(timezone.utc) - timedelta(days=7)
        end = datetime.now(timezone.utc)
        result = _p95_seconds(db, "tid", start, end, property_ids=["prop-1", "prop-2"])
        assert result == 42.0
        # The raw-SQL params dict passed to db.execute must include the property filter
        call_args = db.execute.call_args
        params = call_args[0][1]
        assert params.get("property_ids") == ["prop-1", "prop-2"]


# ──────────────────────────────────────────────────────────────────────────────
# PERF-2: Instagram DM task uses JSONB containment query (not full table scan)
# ──────────────────────────────────────────────────────────────────────────────

class TestInstagramDMGuestLookup:
    def test_no_all_guests_table_scan(self):
        """process_instagram_dm must not load all guests into Python to find one by instagram_id."""
        import app.workers.tasks.process_instagram_dm as ig_module
        source = inspect.getsource(ig_module)
        assert "all_guests" not in source, (
            "process_instagram_dm must not load all_guests into Python; "
            "use a JSONB containment query"
        )

    def test_uses_jsonb_containment_op(self):
        """Guest lookup must use JSONB @> containment operator."""
        import app.workers.tasks.process_instagram_dm as ig_module
        source = inspect.getsource(ig_module)
        assert "@>" in source or "op(\"@>\")" in source, (
            "Guest lookup must use JSONB @> containment instead of iterating all guests"
        )


# ──────────────────────────────────────────────────────────────────────────────
# PERF-3: reports.fetch_team uses aggregate query, not per-user N+1
# ──────────────────────────────────────────────────────────────────────────────

class TestReportsTeamNoN1:
    def test_fetch_team_has_group_by(self):
        """fetch_team must use a GROUP BY aggregate query, not per-user queries in a loop."""
        import app.api.v1.endpoints.reports as reports_module
        source = inspect.getsource(reports_module.fetch_team)
        # Must use group_by for aggregate
        assert "group_by" in source.lower() or "group_by" in source, (
            "fetch_team must use .group_by() aggregate instead of per-user query loop"
        )

    def test_fetch_team_does_not_loop_db_queries(self):
        """fetch_team must not call db.query inside a for-loop over users."""
        import app.api.v1.endpoints.reports as reports_module
        source = inspect.getsource(reports_module.fetch_team)

        # Parse the AST to check for db.query inside for loops
        tree = ast.parse(textwrap.dedent(source))

        class ForLoopDBQueryVisitor(ast.NodeVisitor):
            def __init__(self):
                self.violations = []
                self._in_for = False

            def visit_For(self, node):
                prev = self._in_for
                self._in_for = True
                self.generic_visit(node)
                self._in_for = prev

            def visit_Call(self, node):
                if self._in_for:
                    # Look for db.query(...) inside a for loop
                    if (isinstance(node.func, ast.Attribute)
                            and node.func.attr == "query"
                            and isinstance(node.func.value, ast.Name)
                            and node.func.value.id == "db"):
                        self.violations.append(ast.unparse(node))
                self.generic_visit(node)

        visitor = ForLoopDBQueryVisitor()
        visitor.visit(tree)

        assert not visitor.violations, (
            f"fetch_team has db.query() inside for loop (N+1): {visitor.violations}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# PERF-4: leads_service.get_leads_pipeline batches property-interest lookup
# ──────────────────────────────────────────────────────────────────────────────
# get_leads_pipeline() used to build its property-interest map via
#     {inq.id: get_property_interest(db, tenant_id, inq.id) for inq in inquiries}
# -- a dict comprehension calling a single-inquiry function that issues its
# own db.query() per call. It sat right next to the real _batch_* helpers
# and was named prop_interest_map, so it read like a batch step but was
# actually N individual queries. Direct timing against Ratha's real data
# (683 inquiries) showed page_size=25 taking ~2s and page_size=1000 taking
# ~36s, both wildly outside CLAUDE.md's <200ms budget for this endpoint.
# Fixed via _batch_property_interest(), one query for all inquiry_ids.

class TestLeadsPipelineNoN1:
    def test_get_leads_pipeline_uses_batched_property_interest(self):
        """get_leads_pipeline must call the batched helper, not loop-call the
        single-inquiry get_property_interest per row."""
        import app.services.leads_service as leads_service
        source = inspect.getsource(leads_service.get_leads_pipeline)
        assert "_batch_property_interest(" in source, (
            "get_leads_pipeline must build its property-interest map via _batch_property_interest()"
        )
        assert "get_property_interest(" not in source, (
            "get_leads_pipeline must not call the single-inquiry get_property_interest() per row (N+1)"
        )

    def test_batch_property_interest_issues_single_query(self):
        """_batch_property_interest must fetch all inquiries' calls in one
        query via .in_(inquiry_ids), not one query per inquiry."""
        import app.services.leads_service as leads_service
        source = inspect.getsource(leads_service._batch_property_interest)
        assert ".in_(" in source
        assert source.count("db.query(") == 1, (
            "_batch_property_interest must issue exactly one db.query() call, not one per inquiry"
        )


# ──────────────────────────────────────────────────────────────────────────────
# SEC-4: Messaging list endpoints have safe limits (no unbounded .all())
# ──────────────────────────────────────────────────────────────────────────────

class TestMessagingPagination:
    def test_list_templates_has_limit_param(self):
        import app.api.v1.endpoints.messaging as msg_module
        source = inspect.getsource(msg_module.list_templates)
        assert "limit" in source

    def test_list_campaigns_has_limit_param(self):
        import app.api.v1.endpoints.messaging as msg_module
        source = inspect.getsource(msg_module.list_campaigns)
        assert "limit" in source

    def test_list_subscribers_has_limit_param(self):
        import app.api.v1.endpoints.messaging as msg_module
        source = inspect.getsource(msg_module.list_subscribers)
        assert "limit" in source

    def test_list_flows_has_limit_param(self):
        import app.api.v1.endpoints.messaging as msg_module
        source = inspect.getsource(msg_module.list_flows)
        assert "limit" in source

    def test_list_templates_max_500(self):
        """Template list must be capped at 500 to prevent OOM on large accounts."""
        import app.api.v1.endpoints.messaging as msg_module
        source = inspect.getsource(msg_module.list_templates)
        assert "500" in source


# ──────────────────────────────────────────────────────────────────────────────
# MIGRATION: 017 must exist and contain RLS for wa_* tables
# ──────────────────────────────────────────────────────────────────────────────

class TestMigration017:
    def test_migration_017_exists(self):
        import pathlib
        migrations_dir = pathlib.Path(__file__).parent.parent / "alembic" / "versions"
        files = list(migrations_dir.glob("017_*.py"))
        assert files, "Migration 017 (wa_tables_rls_search_vector) must exist"

    def test_migration_017_has_rls_for_wa_tables(self):
        import pathlib
        migrations_dir = pathlib.Path(__file__).parent.parent / "alembic" / "versions"
        files = list(migrations_dir.glob("017_*.py"))
        assert files
        content = files[0].read_text()
        for table in ("wa_templates", "wa_campaigns", "wa_subscribers", "wa_flows"):
            assert f"ENABLE ROW LEVEL SECURITY" in content
            assert table in content, f"Migration 017 must apply RLS to {table}"

    def test_migration_017_has_search_vector(self):
        import pathlib
        migrations_dir = pathlib.Path(__file__).parent.parent / "alembic" / "versions"
        content = list(migrations_dir.glob("017_*.py"))[0].read_text()
        assert "search_vector" in content, "Migration 017 must add search_vector column to messages"

    def test_migration_017_has_gin_index(self):
        import pathlib
        migrations_dir = pathlib.Path(__file__).parent.parent / "alembic" / "versions"
        content = list(migrations_dir.glob("017_*.py"))[0].read_text()
        assert "GIN" in content, "Migration 017 must create a GIN index on search_vector"
