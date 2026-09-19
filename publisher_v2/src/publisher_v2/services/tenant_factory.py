"""Compatibility re-export (#96): TenantServiceFactory manages WebImageService
instances and therefore belongs to the web layer. Import from
``publisher_v2.web.tenant_factory`` in new code."""

from publisher_v2.web.tenant_factory import TenantServiceFactory, _close_service  # noqa: F401

__all__ = ["TenantServiceFactory"]
