"""
Repository layer.

NOTE ON ARCHITECTURE: app/services/workflow_service.py documents a
deliberate earlier project decision to skip the Repository pattern
entirely for a solo-developer codebase ("plain functions instead of a
class per table"). This package reintroduces a thin repository
specifically for WorkflowRun because a Repository layer was an
explicit requirement of the Workflow Run Management task. It is a
scoped exception for this one table, not a project-wide reversal of
that earlier decision — other tables should keep using the
plain-function service style unless a future task asks for the same
treatment.
"""
