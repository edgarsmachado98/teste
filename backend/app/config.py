from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    database_url: str = "sqlite:///./data/vigia.db"
    evidence_dir: str = "./data/evidencias"
    # Imagens (dado pessoal) são apagadas após retention_days; o registro da ocorrência,
    # sem imagem, fica event_retention_days para os indicadores históricos.
    retention_days: int = 30
    event_retention_days: int = 730

    # Chave para criptografar segredos guardados no banco (ex.: senha do NAS). Se vazia,
    # usa/gera o arquivo secret_key_file.
    secret_key: str = ""
    secret_key_file: str = "./data/secret.key"

    # Chave usada pelo serviço detector para enviar eventos.
    detector_api_key: str = "troque-esta-chave"

    # Endereço público do painel, usado nos links dos alertas.
    public_url: str = "http://localhost:8000"

    # Fuso horário da planta e turnos (para indicadores e mensagens)
    timezone: str = "America/Sao_Paulo"
    shifts: str = "Turno A=06-14,Turno B=14-22,Turno C=22-06"
    session_hours: int = 12
    # Câmera sem imagem por mais que isto (segundos) é considerada offline
    camera_offline_after: int = 60

    # Backup diário do banco (SQLite). BACKUP_COPY_DIR: cópia extra, ex. pasta de rede.
    backup_dir: str = "./data/backups"
    backup_hour: int = 2
    backup_keep: int = 14
    backup_copy_dir: str = ""

    # Logs de auditoria: dias guardados (0 = para sempre)
    audit_retention_days: int = 365
    # Severidade mínima que dispara cada canal (baixa | media | alta | critica); a tela recebe todas
    alert_min_severity_email: str = "baixa"
    alert_min_severity_whatsapp: str = "alta"
    # Alertas de uso do sistema (%) quando o limite é ultrapassado por usage_alert_minutes
    usage_alert_cpu: int = 90
    usage_alert_memory: int = 90
    usage_alert_disk: int = 90
    usage_alert_minutes: int = 5

    # Armazenamento de rede (NAS): pasta compartilhada (\\nas\vigia no Windows, ponto de
    # montagem no Linux). espelho = cópia das evidências; principal = NAS é o armazenamento
    # oficial e o computador guarda só os últimos storage_local_days dias.
    storage_nas_path: str = ""
    storage_mode: str = "espelho"
    storage_local_days: int = 7
    storage_nas_user: str = ""
    storage_nas_password: str = ""
    storage_sync_interval: int = 60
    storage_backup_keep: int = 60
    storage_offline_alert_minutes: int = 10

    # Relatório automático por e-mail: mensal | semanal | desligado
    report_frequency: str = "mensal"
    report_hour: int = 7
    report_emails: str = ""  # vazio = usa ALERT_EMAILS
    company_name: str = ""  # aparece no cabeçalho do relatório

    @property
    def report_recipients(self) -> list[str]:
        emails = self.report_emails or self.alert_emails
        return [e.strip() for e in emails.split(",") if e.strip()]

    # E-mail (SMTP)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_tls: bool = True
    alert_emails: str = ""  # separados por vírgula

    # WhatsApp Business Cloud API (Meta)
    whatsapp_token: str = ""
    whatsapp_phone_id: str = ""
    whatsapp_to: str = ""  # números com DDI, separados por vírgula
    whatsapp_template: str = ""  # opcional; necessário fora da janela de 24h
    whatsapp_template_lang: str = "pt_BR"

    @property
    def email_recipients(self) -> list[str]:
        return [e.strip() for e in self.alert_emails.split(",") if e.strip()]

    @property
    def whatsapp_recipients(self) -> list[str]:
        return [n.strip() for n in self.whatsapp_to.split(",") if n.strip()]


settings = Settings()
