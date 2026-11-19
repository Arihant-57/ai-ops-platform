"""
agent-service – database models (SQLAlchemy 2.0 async)
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    daily_token_budget = Column(Integer, nullable=False, default=500_000)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    members = relationship("TeamMember", back_populates="team_ref", cascade="all, delete-orphan")


class TeamMember(Base):
    __tablename__ = "team_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(150), nullable=False)
    email = Column(String(200), nullable=True)
    role = Column(String(50), nullable=False, default="developer")  # admin | developer | viewer
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    team_ref = relationship("Team", back_populates="members")


class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    owner_team = Column(String(100), nullable=False, default="default")
    model = Column(String(100), nullable=False)
    daily_token_budget = Column(Integer, nullable=False, default=100_000)
    budget_mode = Column(String(10), nullable=False, default="soft")  # soft | hard
    status = Column(String(10), nullable=False, default="ACTIVE")  # ACTIVE | INACTIVE
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
