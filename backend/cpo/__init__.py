"""ChargePlus CPO Integration Module.

Commercial Charge Point Operator integrations via OCPI 2.2.1 and OICP 2.3
(eRoaming subset). All partner data flows through the existing canonical
ingestion pipeline (validation → resolution → deduplication → persistence);
adapters never write to the database directly.

Every partner starts NOT_CONFIGURED. No production state is claimed without
real credentials, partner approval, and a successful authorized exchange —
see docs/cpo_partners.md for the activation checklist.
"""
