from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/vigia.db"
    evidence_dir: str = "./data/evidencias"
    retention_days: int = 30

    # Token do painel/API. Vazio = sem autenticação (apenas desenvolvimento).
    api_token: str = ""
    # Chave usada pelo serviço detector para enviar eventos.
    detector_api_key: str = "troque-esta-chave"

    # Endereço público do painel, usado nos links dos alertas.
    public_url: str = "http://localhost:8000"

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
