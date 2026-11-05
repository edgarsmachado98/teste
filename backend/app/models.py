from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base, UTCDateTime


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Perfis em ordem crescente de permissão
ROLES = ("operador", "tecnico", "gestor", "admin")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20), default="operador")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # Guardamos só o hash do token: um vazamento do banco não dá acesso ao sistema.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)

    user: Mapped[User] = relationship()


class AuditLog(Base):
    """Registro de quem fez o quê (LGPD e rastreabilidade das ocorrências)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    user_name: Mapped[str] = mapped_column(String(120), default="sistema")
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str] = mapped_column(String(40), default="")
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    details: Mapped[str] = mapped_column(Text, default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class Unit(Base):
    """Unidade (planta) do cliente."""

    __tablename__ = "units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Sector(Base):
    """Setor com o seu padrão de segurança: EPI obrigatório e regras de comportamento.
    Ao aplicar o padrão, as regras de detecção das câmeras do setor são geradas."""

    __tablename__ = "sectors"
    __table_args__ = (UniqueConstraint("unit_id", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    # EPI verificado pela câmera (helmet, vest, glasses, gloves, mask)
    required_ppe: Mapped[list] = mapped_column(JSON, default=list)
    # EPI só com controle de entrega (a câmera não identifica com segurança), ex.: "Botina"
    delivery_ppe: Mapped[list] = mapped_column(JSON, default=list)
    # Exames ocupacionais exigidos de quem trabalha no setor (códigos de exams.CATALOG)
    required_exams: Mapped[list] = mapped_column(JSON, default=list)
    ppe_severity: Mapped[str] = mapped_column(String(20), default="alta")
    # {"restricted_zone": {"enabled", "severity"}, "max_people": {"enabled", "max", "severity"},
    #  "fire_smoke": {"enabled", "severity"}}
    behaviors: Mapped[dict] = mapped_column(JSON, default=dict)
    start_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference: Mapped[str] = mapped_column(String(200), default="")  # ex.: OS-SOL-03 · NR-6
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_by: Mapped[str] = mapped_column(String(120), default="")

    unit: Mapped[Unit] = relationship()


PERSON_STATUSES = ("ativo", "afastado", "desligado")
EMPLOYMENTS = ("clt", "terceiro", "temporario", "estagiario")


class Person(Base):
    """Colaborador ou terceiro. Dados mínimos para a segurança (LGPD): sem endereço, telefone
    ou data de nascimento. A foto serve só para identificação visual pela equipe."""

    __tablename__ = "people"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"))
    sector_id: Mapped[int | None] = mapped_column(ForeignKey("sectors.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    cpf: Mapped[str] = mapped_column(String(11), unique=True)  # só dígitos
    registration: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True)  # matrícula
    role: Mapped[str] = mapped_column(String(120), default="")  # função
    shift: Mapped[str] = mapped_column(String(60), default="")
    employment: Mapped[str] = mapped_column(String(20), default="clt")
    company: Mapped[str] = mapped_column(String(160), default="")  # prestadora (terceiros)
    manager: Mapped[str] = mapped_column(String(160), default="")
    # Número do colete/capacete/crachá (identificação sem biometria)
    badge_code: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True)
    photo_file: Mapped[str | None] = mapped_column(String(200), nullable=True)
    photo_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    photo_consent_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Tamanhos para EPI e uniforme, ex.: {"camisa": "G", "calca": "42", "calcado": "40", "luva": "9"}
    sizes: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="ativo")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    unit: Mapped["Unit"] = relationship()
    sector: Mapped["Sector | None"] = relationship()
    deliveries: Mapped[list["PPEDelivery"]] = relationship(cascade="all, delete-orphan", order_by="PPEDelivery.delivered_on.desc()")
    trainings: Mapped[list["TrainingRecord"]] = relationship(cascade="all, delete-orphan", order_by="TrainingRecord.id.desc()")
    exams: Mapped[list["ExamRecord"]] = relationship(cascade="all, delete-orphan",
                                                     order_by="(ExamRecord.performed_on.desc(), ExamRecord.id.desc())")


class PPEDelivery(Base):
    """EPI ou uniforme entregue a uma pessoa. `valid_until` = troca prevista; `replaced_on` = quando foi
    substituído por uma entrega nova do mesmo item (deixa de contar nos vencimentos)."""

    __tablename__ = "ppe_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"))
    item: Mapped[str] = mapped_column(String(120))
    ca: Mapped[str] = mapped_column(String(20), default="")  # certificado de aprovação
    delivered_on: Mapped[date] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("ppe_items.id", ondelete="SET NULL"), nullable=True)
    category: Mapped[str | None] = mapped_column(String(20), nullable=True, default="epi")  # epi | uniforme
    size: Mapped[str | None] = mapped_column(String(20), nullable=True, default="")
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1)
    reason: Mapped[str | None] = mapped_column(String(20), nullable=True, default="")
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("units.id", ondelete="SET NULL"), nullable=True)
    receipt_id: Mapped[int | None] = mapped_column(ForeignKey("ppe_receipts.id", ondelete="SET NULL"), nullable=True,
                                                   index=True)
    from_stock: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)
    replaced_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, default=utcnow)

    receipt: Mapped["PPEReceipt | None"] = relationship(back_populates="deliveries")


PPE_CATEGORIES = ("epi", "uniforme")
DELIVERY_REASONS = {
    "primeira": "Primeira entrega / admissão",
    "troca": "Troca periódica",
    "desgaste": "Desgaste ou dano",
    "perda": "Perda ou extravio",
    "tamanho": "Troca de tamanho",
    "outro": "Outro",
}
MOVE_TYPES = {"entrada": "Entrada (compra)", "saida": "Entrega", "ajuste": "Ajuste de inventário",
              "devolucao": "Devolução", "estorno": "Estorno de entrega"}


class PPEItem(Base):
    """Catálogo de EPIs e uniformes (com o CA – Certificado de Aprovação – e a troca periódica)."""

    __tablename__ = "ppe_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(20), default="epi")
    ppe_type: Mapped[str] = mapped_column(String(30), default="")  # helmet, vest... (o que a câmera cobra)
    ca: Mapped[str] = mapped_column(String(20), default="")
    ca_valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    manufacturer: Mapped[str] = mapped_column(String(120), default="")
    sizes: Mapped[list] = mapped_column(JSON, default=list)  # ex.: ["P", "M", "G"]; vazio = tamanho único
    replacement_days: Mapped[int | None] = mapped_column(Integer, nullable=True)  # troca periódica
    unit_label: Mapped[str] = mapped_column(String(10), default="un")  # un, par, cx
    unit_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class PPEStock(Base):
    """Saldo de um item (e tamanho) numa unidade, com o estoque mínimo."""

    __tablename__ = "ppe_stock"
    __table_args__ = (UniqueConstraint("unit_id", "item_id", "size"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("ppe_items.id", ondelete="CASCADE"), index=True)
    size: Mapped[str] = mapped_column(String(20), default="")
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    min_quantity: Mapped[int] = mapped_column(Integer, default=0)
    location: Mapped[str] = mapped_column(String(80), default="")  # almoxarifado, armário...

    item: Mapped[PPEItem] = relationship(lazy="selectin")
    unit: Mapped[Unit] = relationship(lazy="selectin")


class PPEMovement(Base):
    """Histórico do estoque: entradas, entregas, ajustes e devoluções (rastreabilidade)."""

    __tablename__ = "ppe_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("ppe_items.id", ondelete="CASCADE"), index=True)
    size: Mapped[str] = mapped_column(String(20), default="")
    type: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[int] = mapped_column(Integer)  # positivo entra, negativo sai
    balance: Mapped[int] = mapped_column(Integer)  # saldo depois do movimento
    note: Mapped[str] = mapped_column(String(300), default="")  # nota fiscal, fornecedor, motivo
    person_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"), nullable=True)
    receipt_id: Mapped[int | None] = mapped_column(ForeignKey("ppe_receipts.id", ondelete="SET NULL"), nullable=True)
    user_name: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)

    item: Mapped[PPEItem] = relationship(lazy="selectin")


SIGN_METHODS = {"tela": "Assinatura na tela", "impressa": "Ficha impressa e assinada no papel",
                "biometria": "Biometria (leitor de digital)"}


class PPEReceipt(Base):
    """Comprovante de entrega (ficha de EPI – NR-6): uma ou mais peças entregues de uma vez e a confirmação
    do colaborador. A assinatura eletrônica guarda a imagem, a foto do momento (opcional), data/hora, IP e
    o hash SHA-256 do conteúdo – qualquer alteração posterior é detectada."""

    __tablename__ = "ppe_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)  # EPI-2026-0001
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("units.id", ondelete="SET NULL"), nullable=True)
    delivered_on: Mapped[date] = mapped_column(Date)
    method: Mapped[str] = mapped_column(String(20), default="pendente")  # tela | impressa | biometria | pendente
    signature_file: Mapped[str | None] = mapped_column(String(200), nullable=True)
    photo_file: Mapped[str | None] = mapped_column(String(200), nullable=True)
    biometric_ref: Mapped[str] = mapped_column(String(200), default="")  # id da verificação no leitor
    identity_check: Mapped[str] = mapped_column(String(60), default="")  # ex.: "CPF conferido"
    signed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(String(500), default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    person: Mapped["Person"] = relationship(lazy="selectin")
    created_by: Mapped[User | None] = relationship(lazy="selectin")
    deliveries: Mapped[list[PPEDelivery]] = relationship(back_populates="receipt", lazy="selectin",
                                                         order_by="PPEDelivery.id")


TRAINING_STATUSES = ("agendado", "concluido", "cancelado")


class TrainingRecord(Base):
    __tablename__ = "trainings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(160))
    scheduled_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="agendado")
    measure_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ExamRecord(Base):
    """Exame ocupacional (PCMSO – NR-7). Só datas e aptidão: sem diagnóstico (LGPD, dado sensível)."""

    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    exam: Mapped[str] = mapped_column(String(30))  # aso, audiometria, espirometria...
    aso_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # admissional, periodico...
    performed_on: Mapped[date] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    result: Mapped[str | None] = mapped_column(String(20), nullable=True)  # apto | apto_restricao | inapto
    restrictions: Mapped[str] = mapped_column(String(300), default="")  # restrição funcional, nunca diagnóstico
    aptitudes: Mapped[list] = mapped_column(JSON, default=list)  # altura, espaco_confinado, eletricidade...
    provider: Mapped[str] = mapped_column(String(160), default="")  # clínica / médico examinador
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    location: Mapped[str] = mapped_column(String(120), default="")
    # URL RTSP/HTTP ou caminho de arquivo de vídeo (para testes)
    source: Mapped[str] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    # Saúde: ok | offline | escura | obstruida | congelada (None = ainda sem imagem)
    health: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_frame_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # Motivo de o detector não conseguir abrir a câmera (rede, senha, caminho, codec); vazio quando conecta
    connect_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    connect_error_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    sector_id: Mapped[int | None] = mapped_column(ForeignKey("sectors.id", ondelete="SET NULL"), nullable=True)
    # Unidade (planta) da câmera: a do setor, ou escolhida quando a câmera não tem setor
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("units.id", ondelete="SET NULL"), nullable=True, index=True)

    sector: Mapped[Sector | None] = relationship()
    unit: Mapped[Unit | None] = relationship()
    rules: Mapped[list["Rule"]] = relationship(back_populates="camera", cascade="all, delete-orphan")


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    # ppe_missing | restricted_zone | fire_smoke | max_people
    type: Mapped[str] = mapped_column(String(40))
    # Polígono com coordenadas normalizadas (0..1). Vazio = imagem inteira.
    zone: Mapped[list] = mapped_column(JSON, default=list)
    # Parâmetros específicos do tipo, ex.: {"required": ["helmet", "vest"]}
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    min_confidence: Mapped[float] = mapped_column(Float, default=0.5)
    min_duration: Mapped[float] = mapped_column(Float, default=2.0)  # segundos
    cooldown: Mapped[float] = mapped_column(Float, default=300.0)  # segundos
    start_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    severity: Mapped[str] = mapped_column(String(20), default="alta")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Regra gerada pelo padrão de um setor (None = criada manualmente)
    sector_id: Mapped[int | None] = mapped_column(ForeignKey("sectors.id", ondelete="SET NULL"), nullable=True)
    # Aviso do detector (ex.: nenhum modelo carregado reconhece capacete: a regra não acusa ninguém)
    warning: Mapped[str | None] = mapped_column(String(300), nullable=True)

    camera: Mapped[Camera] = relationship(back_populates="rules")


# Fluxo da ocorrência: nova -> confirmada | descartada -> encerrada
EVENT_STATUSES = ("nova", "confirmada", "descartada", "encerrada")
CLASSIFICATIONS = ("ato_inseguro", "condicao_insegura", "quase_acidente", "acidente")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"))
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("rules.id", ondelete="SET NULL"), nullable=True)
    type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(String(500))
    image_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Clipe (sequência de quadros JPEG) de alguns segundos antes e depois do desvio
    clip_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    clip_dir: Mapped[str | None] = mapped_column(String(255), nullable=True)
    clip_frames: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clip_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Quando a foto e o clipe foram copiados para o armazenamento de rede (NAS)
    media_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="nova")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    # Caixas normalizadas das pessoas/objetos em violação (usadas no mapa de calor)
    boxes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Imagem e clipe guardados no storage do cliente, servidos pelo VigIA Edge sob demanda.
    # image_file/clip_dir são então caminhos relativos no Edge; a miniatura fica aqui.
    media_edge_id: Mapped[int | None] = mapped_column(ForeignKey("edges.id", ondelete="SET NULL"), nullable=True)
    thumb_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    clip_format: Mapped[str | None] = mapped_column(String(10), nullable=True)  # None/jpg = quadros · webm = vídeo
    edge_ref: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)  # evita duplicar no reenvio
    classification: Mapped[str | None] = mapped_column(String(30), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # Pessoa envolvida, identificada por um técnico (lista | numero | busca | nao_identificado)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"), nullable=True, index=True)
    identification: Mapped[str | None] = mapped_column(String(20), nullable=True)
    identified_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    identified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    camera: Mapped[Camera] = relationship()
    rule: Mapped[Rule | None] = relationship()
    reviewed_by: Mapped[User | None] = relationship(foreign_keys=[reviewed_by_id])
    identified_by: Mapped[User | None] = relationship(foreign_keys=[identified_by_id])
    person: Mapped["Person | None"] = relationship()
    actions: Mapped[list["ActionItem"]] = relationship(back_populates="event")


ACTION_STATUSES = ("aberta", "concluida", "cancelada")


class ActionItem(Base):
    """Ação do plano de ação (corretiva ou preventiva)."""

    __tablename__ = "actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    responsible_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="aberta")
    completion_notes: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    event: Mapped[Event | None] = relationship(back_populates="actions")
    responsible: Mapped[User | None] = relationship(foreign_keys=[responsible_id])
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="action", cascade="all, delete-orphan", lazy="selectin", order_by="Attachment.id")


ATTACHMENT_KINDS = {
    "advertencia_assinada": "Advertência assinada",
    "dds": "Registro de DDS / lista de presença",
    "ata_treinamento": "Ata de treinamento / reciclagem",
    "evidencia": "Foto ou evidência da correção",
    "outro": "Outro documento",
}


class Attachment(Base):
    """Documento anexado a uma ação do plano (ex.: advertência assinada, ata de reciclagem)."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action_id: Mapped[int] = mapped_column(ForeignKey("actions.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30), default="outro")
    filename: Mapped[str] = mapped_column(String(200))  # nome original, só para exibição
    file: Mapped[str] = mapped_column(String(200))  # caminho relativo à pasta de evidências
    content_type: Mapped[str] = mapped_column(String(60))
    size: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    action: Mapped[ActionItem] = relationship(back_populates="attachments")
    uploaded_by: Mapped[User | None] = relationship(lazy="selectin")


MEASURE_TYPES = ("orientacao", "treinamento", "advertencia", "rh")
MEASURE_STATUSES = ("pendente_aprovacao", "aplicada", "cancelada")
ACK_STATUSES = ("pendente", "assinada", "impressa", "recusada")


class Measure(Base):
    """Medida educativa ou disciplinar aplicada a partir de uma ocorrência."""

    __tablename__ = "measures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)  # VIG-2026-0001
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"), nullable=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(20))
    suggested_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    justification: Mapped[str] = mapped_column(Text, default="")  # quando diferente da sugerida
    description: Mapped[str] = mapped_column(Text, default="")
    training_name: Mapped[str] = mapped_column(String(160), default="")
    training_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="aplicada")
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    ack: Mapped[str] = mapped_column(String(20), default="pendente")
    signature_file: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ack_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    statement: Mapped[str] = mapped_column(Text, default="")  # versão dos fatos do colaborador
    witnesses: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    event: Mapped["Event | None"] = relationship()
    person: Mapped["Person"] = relationship()
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    approved_by: Mapped[User | None] = relationship(foreign_keys=[approved_by_id])


class Edge(Base):
    """VigIA Edge: caixa local do cliente (detector + imagens no storage do cliente) ligada a esta
    instância na nuvem por um túnel de saída. Só os dados da ocorrência e a miniatura sobem."""

    __tablename__ = "edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id", ondelete="CASCADE"))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)  # credencial do Edge (só o hash)
    cert_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)  # mTLS (SHA-256 do certificado)
    lan_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)  # assina os links de acesso direto (cifrada)
    enrolled_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    version: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[dict] = mapped_column(JSON, default=dict)  # disco, fila, storage, câmeras

    unit: Mapped[Unit] = relationship(lazy="selectin")


class EdgeMediaKey(Base):
    """Cópia (cifrada com a chave da instância) das chaves AES das imagens gravadas pelos Edges de uma
    unidade: se a máquina do Edge for trocada, o Edge novo continua lendo as imagens antigas do storage."""

    __tablename__ = "edge_media_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id", ondelete="CASCADE"), index=True)
    kid: Mapped[str] = mapped_column(String(8), unique=True)
    key_enc: Mapped[str] = mapped_column(Text)
    edge_id: Mapped[int | None] = mapped_column(ForeignKey("edges.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class EdgeEnrollment(Base):
    """Código de instalação de uso único (vale 24 h) para cadastrar um Edge."""

    __tablename__ = "edge_enrollments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class DDSTheme(Base):
    """Tema de DDS (Diálogo Diário de Segurança): de referência (code) ou criado pela empresa."""

    __tablename__ = "dds_themes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True)  # temas de referência
    category: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(200))
    reference: Mapped[str] = mapped_column(String(120), default="")  # NR
    points: Mapped[list] = mapped_column(JSON, default=list)  # roteiro para quem conduz
    question: Mapped[str] = mapped_column(String(300), default="")  # pergunta para a equipe
    minutes: Mapped[int] = mapped_column(Integer, default=10)
    triggers: Mapped[list] = mapped_column(JSON, default=list)  # ocorrências que tornam o tema prioritário
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class DDSSession(Base):
    """DDS programado ou realizado num setor/turno."""

    __tablename__ = "dds_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id", ondelete="CASCADE"), index=True)
    sector_id: Mapped[int | None] = mapped_column(ForeignKey("sectors.id", ondelete="SET NULL"), nullable=True)
    shift: Mapped[str] = mapped_column(String(60), default="")
    day: Mapped[date] = mapped_column(Date, index=True)
    theme_id: Mapped[int | None] = mapped_column(ForeignKey("dds_themes.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))  # cópia do tema (o histórico não muda se o tema mudar)
    facilitator: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(20), default="planejado")  # planejado | realizado | cancelado
    reason: Mapped[str] = mapped_column(String(200), default="")  # por que o tema foi escolhido
    notes: Mapped[str] = mapped_column(Text, default="")
    extra_participants: Mapped[int] = mapped_column(Integer, default=0)  # terceiros/visitantes sem cadastro
    held_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    recorded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    theme: Mapped[DDSTheme | None] = relationship(lazy="selectin")
    unit: Mapped[Unit] = relationship(lazy="selectin")
    sector: Mapped[Sector | None] = relationship(lazy="selectin")
    attendance: Mapped[list["DDSAttendance"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class DDSAttendance(Base):
    __tablename__ = "dds_attendance"
    __table_args__ = (UniqueConstraint("session_id", "person_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("dds_sessions.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)


class StorageDeletion(Base):
    """Exclusão pendente no NAS (retenção/LGPD) para quando ele estiver acessível."""

    __tablename__ = "storage_deletions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rel_path: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class SystemState(Base):
    """Pares chave/valor do sistema (ex.: data do último backup e do último relatório enviado)."""

    __tablename__ = "system_state"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class RuleStat(Base):
    """Observações agregadas por hora: base do índice de conformidade de EPI.

    `observed` = pessoas observadas na zona (somadas por quadro analisado);
    `violations` = quantas dessas estavam sem algum EPI obrigatório."""

    __tablename__ = "rule_stats"
    __table_args__ = (UniqueConstraint("rule_id", "hour"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("rules.id", ondelete="CASCADE"))
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"))
    hour: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    observed: Mapped[int] = mapped_column(Integer, default=0)
    violations: Mapped[int] = mapped_column(Integer, default=0)
