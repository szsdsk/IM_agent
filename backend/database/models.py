import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship

from backend.database.connection import Base


def generate_id():
    return str(uuid.uuid4())


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True, default=generate_id)
    session_id = Column(String(36), nullable=False, index=True)
    intent = Column(Text, nullable=False)
    status = Column(String(20), default="pending")
    current_step = Column(String(50), nullable=True)
    result_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    documents = relationship("Document", back_populates="task")
    slides = relationship("Slide", back_populates="task")
    events = relationship("Event", back_populates="task")

    @property
    def progress(self):
        if isinstance(self.result_json, dict):
            return self.result_json.get("progress", 0.0)
        return 0.0


class Document(Base):
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=generate_id)
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=False)
    content = Column(Text, nullable=True)
    version = Column(Integer, default=1)
    lark_doc_id = Column(String(100), nullable=True, index=True)
    lark_doc_url = Column(String(500), nullable=True)
    last_edited_by = Column(String(100), nullable=True)
    last_edited_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    task = relationship("Task", back_populates="documents")


class Slide(Base):
    __tablename__ = "slides"

    id = Column(String(36), primary_key=True, default=generate_id)
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=False)
    slides_json = Column(JSON, nullable=True)
    file_path = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    task = relationship("Task", back_populates="slides")


class Event(Base):
    __tablename__ = "events"

    id = Column(String(36), primary_key=True, default=generate_id)
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=False)
    event_type = Column(String(50), nullable=False)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    task = relationship("Task", back_populates="events")


class Session(Base):
    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True, default=generate_id)
    user_id = Column(String(100), nullable=True)
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
