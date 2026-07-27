"""
Declarative base for all ORM models.

Sprint 2 adds: Project, Video, Script, Storyboard, Image, GeneratedVideo,
Asset, Provider, WorkflowRun, Artifact, Prompt, Analytics, LearningFeedback,
SystemLog — each as its own model module under app/models/, importing Base
from here so Alembic autogenerate can discover them all.
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
