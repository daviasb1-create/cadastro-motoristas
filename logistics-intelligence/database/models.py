"""Modelo de dados (SQLAlchemy 2.x). Compatível com SQLite e PostgreSQL."""
from __future__ import annotations

from datetime import datetime, date

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint, Index)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from services.timeutil import now


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "empresas"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255), index=True)
    cnpj: Mapped[str | None] = mapped_column(String(14), index=True, unique=True)
    domain: Mapped[str | None] = mapped_column(String(255), index=True)
    website: Mapped[str | None] = mapped_column(String(500))
    segment: Mapped[str | None] = mapped_column(String(120))
    city: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(2))
    address: Mapped[str | None] = mapped_column(String(500))
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    legal_name: Mapped[str | None] = mapped_column(String(255))
    cnae: Mapped[str | None] = mapped_column(String(255))
    field_sources: Mapped[dict] = mapped_column(JSON, default=dict)  # campo -> fonte
    opt_out: Mapped[bool] = mapped_column(Boolean, default=False)  # LGPD: descadastro
    opt_out_reason: Mapped[str | None] = mapped_column(String(500))
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    contacts: Mapped[list["Contact"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    opportunities: Mapped[list["Opportunity"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    lead: Mapped["Lead | None"] = relationship(back_populates="company", uselist=False, cascade="all, delete-orphan")


class Contact(Base):
    __tablename__ = "contatos"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str | None] = mapped_column(String(255))
    department: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(40))
    whatsapp: Mapped[str | None] = mapped_column(String(40))
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    source_name: Mapped[str | None] = mapped_column(String(120))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    is_corporate: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    company: Mapped[Company] = relationship(back_populates="contacts")


class Opportunity(Base):
    __tablename__ = "oportunidades"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(500))
    category: Mapped[str] = mapped_column(String(40), index=True)
    service_type: Mapped[str | None] = mapped_column(String(255))
    origin: Mapped[str | None] = mapped_column(String(120))
    destination: Mapped[str | None] = mapped_column(String(120))
    frequency: Mapped[str | None] = mapped_column(String(40))
    vehicle_types: Mapped[str | None] = mapped_column(String(255))
    volume: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[str | None] = mapped_column(Text)
    demand_level: Mapped[str | None] = mapped_column(String(20))  # explicita | forte | indicio | perfil
    source_name: Mapped[str] = mapped_column(String(120))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    deadline: Mapped[datetime | None] = mapped_column(DateTime)
    found_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    score_breakdown: Mapped[list] = mapped_column(JSON, default=list)
    priority: Mapped[str] = mapped_column(String(40), default="Baixa prioridade")
    next_action: Mapped[str | None] = mapped_column(Text)
    extraction_method: Mapped[str] = mapped_column(String(20), default="heuristica")
    estimated_value: Mapped[float | None] = mapped_column(Float)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("pesquisas.id"))
    company: Mapped[Company] = relationship(back_populates="opportunities")


class Lead(Base):
    __tablename__ = "leads"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), unique=True)
    status: Mapped[str] = mapped_column(String(60), default="Novo lead", index=True)
    owner: Mapped[str | None] = mapped_column(String(120))
    score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    priority: Mapped[str] = mapped_column(String(40), default="Baixa prioridade")
    recommended_service: Mapped[str | None] = mapped_column(String(255))
    monthly_potential: Mapped[float | None] = mapped_column(Float)
    quote_value: Mapped[float | None] = mapped_column(Float)
    routes: Mapped[str | None] = mapped_column(String(500))
    loss_reason: Mapped[str | None] = mapped_column(String(500))
    next_contact_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_approach_at: Mapped[datetime | None] = mapped_column(DateTime)
    first_contact_at: Mapped[datetime | None] = mapped_column(DateTime)
    responded: Mapped[bool] = mapped_column(Boolean, default=False)
    campaign_approved: Mapped[bool] = mapped_column(Boolean, default=False)  # aprovação humana
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    company: Mapped[Company] = relationship(back_populates="lead")
    history: Mapped[list["History"]] = relationship(back_populates="lead", cascade="all, delete-orphan",
                                                    order_by="History.created_at.desc()")
    messages: Mapped[list["Message"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    followups: Mapped[list["FollowUp"]] = relationship(back_populates="lead", cascade="all, delete-orphan")


class PipelineEvent(Base):
    """Mudanças de etapa do funil (base da taxa de conversão)."""
    __tablename__ = "pipeline"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(60))
    to_status: Mapped[str] = mapped_column(String(60))
    changed_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class History(Base):
    __tablename__ = "historico"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))  # nota, conversa, abordagem, status, descoberta, sistema
    channel: Mapped[str | None] = mapped_column(String(40))
    content: Mapped[str] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    lead: Mapped[Lead] = relationship(back_populates="history")


class Message(Base):
    """Abordagens geradas (sempre rascunho até o usuário registrar o envio)."""
    __tablename__ = "mensagens"
    __table_args__ = (UniqueConstraint("lead_id", "channel", "stage", name="uq_msg_lead_canal_etapa"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("oportunidades.id"))
    channel: Mapped[str] = mapped_column(String(20))  # email | whatsapp
    stage: Mapped[str] = mapped_column(String(40), default="primeiro_contato")
    template_key: Mapped[str | None] = mapped_column(String(60))
    recipient: Mapped[str | None] = mapped_column(String(255))
    recipient_name: Mapped[str | None] = mapped_column(String(255))
    recipient_role: Mapped[str | None] = mapped_column(String(255))
    subject: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    generated_by: Mapped[str] = mapped_column(String(20), default="modelo")  # ia | modelo
    status: Mapped[str] = mapped_column(String(20), default="rascunho")  # rascunho | enviado | descartado
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    outlook_draft_id: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    lead: Mapped[Lead] = relationship(back_populates="messages")


class FollowUp(Base):
    __tablename__ = "followups"
    __table_args__ = (UniqueConstraint("lead_id", "stage", name="uq_followup_lead_etapa"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    stage: Mapped[str] = mapped_column(String(40))
    due_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pendente")  # pendente | feito | cancelado
    done_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    lead: Mapped[Lead] = relationship(back_populates="followups")


class Route(Base):
    """Rotas/operações detectadas em oportunidades."""
    __tablename__ = "rotas"
    __table_args__ = (UniqueConstraint("opportunity_id", "origin", "destination", name="uq_rota"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("oportunidades.id"), index=True)
    origin: Mapped[str] = mapped_column(String(120))
    destination: Mapped[str] = mapped_column(String(120))
    matches_served_route: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Source(Base):
    __tablename__ = "fontes"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    daily_limit: Mapped[int] = mapped_column(Integer, default=50)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_status: Mapped[str | None] = mapped_column(String(40))  # ok | erro | indisponivel | sem_credencial
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)


class ApiUsage(Base):
    __tablename__ = "consumo_api"
    __table_args__ = (UniqueConstraint("day", "source_key", name="uq_consumo_dia_fonte"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    source_key: Mapped[str] = mapped_column(String(60))
    calls: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    web_searches: Mapped[int] = mapped_column(Integer, default=0)


class SearchRun(Base):
    __tablename__ = "pesquisas"
    id: Mapped[int] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(String(20), default="completa")  # completa | urgente
    trigger: Mapped[str] = mapped_column(String(20), default="manual")  # manual | agendado | github
    status: Mapped[str] = mapped_column(String(20), default="executando")  # executando | ok | parcial | erro
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    results_found: Mapped[int] = mapped_column(Integer, default=0)
    results_relevant: Mapped[int] = mapped_column(Integer, default=0)
    new_companies: Mapped[int] = mapped_column(Integer, default=0)
    new_opportunities: Mapped[int] = mapped_column(Integer, default=0)
    messages_generated: Mapped[int] = mapped_column(Integer, default=0)
    alerts_sent: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)


class SeenItem(Base):
    """Todo resultado bruto já processado (evita reprocessar e gastar API)."""
    __tablename__ = "itens_vistos"
    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    source_key: Mapped[str] = mapped_column(String(60))
    url: Mapped[str | None] = mapped_column(String(1000))
    title: Mapped[str | None] = mapped_column(String(500))
    relevant: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=now)


class Notification(Base):
    __tablename__ = "notificacoes"
    __table_args__ = (UniqueConstraint("opportunity_id", "channel", name="uq_notif_opp_canal"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("oportunidades.id"), index=True)
    channel: Mapped[str] = mapped_column(String(20))
    level: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))  # enviado | erro
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Setting(Base):
    __tablename__ = "configuracoes"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict | list | str | int | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class Template(Base):
    __tablename__ = "modelos"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    channel: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class ExecutionLog(Base):
    __tablename__ = "logs_execucao"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("pesquisas.id"), index=True)
    level: Mapped[str] = mapped_column(String(10))
    component: Mapped[str] = mapped_column(String(60))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


Index("ix_opp_company_found", Opportunity.company_id, Opportunity.found_at)


# Corta textos maiores que a coluna (o PostgreSQL rejeita; o SQLite aceitaria em silêncio)
from sqlalchemy import event as _event  # noqa: E402


def _truncate_strings(mapper, connection, target) -> None:  # noqa: ANN001
    for col in mapper.columns:
        length = getattr(col.type, "length", None)
        if length and isinstance(col.type, String):
            val = getattr(target, col.key, None)
            if isinstance(val, str) and len(val) > length:
                setattr(target, col.key, val[:length])


_event.listen(Base, "before_insert", _truncate_strings, propagate=True)
_event.listen(Base, "before_update", _truncate_strings, propagate=True)
