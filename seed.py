"""Dados iniciais: tipos de orçamento, seções e itens sugeridos.

Os itens entram no catálogo com custo zero; os preços são preenchidos pelo usuário.
"""

EMPRESA = {
    "nome": "Minha Empresa",
    "apresentacao": (
        "Somos especializados em infraestrutura de rede, segurança eletrônica "
        "e equipamentos de TI. Edite este texto em Empresa."
    ),
    "pagamento": "A combinar.",
    "prazo": "A combinar após aprovação.",
    "garantia": "Equipamentos: garantia do fabricante. Serviços: 90 dias.",
}

# (descrição, unidade, categoria, tipo)  tipo: "produto" ou "servico"
TIPOS = [
    {
        "nome": "Infraestrutura de rede",
        "escopo": "Fornecimento e instalação de infraestrutura de rede estruturada.",
        "nao_incluso": "Obras civis, pintura e pontos elétricos.",
        "secoes": [
            ("Cabeamento", [
                ("Cabo UTP Cat6", "m", "Cabos e acessórios", "produto"),
                ("Conector keystone Cat6", "un", "Cabos e acessórios", "produto"),
                ("Patch cord Cat6 1,5 m", "un", "Cabos e acessórios", "produto"),
                ("Eletroduto / canaleta", "m", "Cabos e acessórios", "produto"),
            ]),
            ("Rack e organização", [
                ("Rack de rede", "un", "Rede", "produto"),
                ("Patch panel 24 portas Cat6", "un", "Rede", "produto"),
                ("Organizador de cabos", "un", "Rede", "produto"),
            ]),
            ("Ativos", [
                ("Switch 24 portas", "un", "Rede", "produto"),
                ("Access point", "un", "Rede", "produto"),
            ]),
            ("Serviços", [
                ("Instalação de ponto de rede", "ponto", "Serviços", "servico"),
                ("Certificação de pontos", "ponto", "Serviços", "servico"),
            ]),
        ],
    },
    {
        "nome": "Câmeras (CFTV)",
        "escopo": "Fornecimento e instalação de sistema de câmeras de segurança.",
        "nao_incluso": "Obras civis, pontos elétricos e link de internet.",
        "secoes": [
            ("Câmeras", [
                ("Câmera IP dome", "un", "Câmeras", "produto"),
                ("Câmera IP bullet", "un", "Câmeras", "produto"),
            ]),
            ("Gravação e armazenamento", [
                ("NVR", "un", "Câmeras", "produto"),
                ("HD para gravação", "un", "Câmeras", "produto"),
            ]),
            ("Infraestrutura", [
                ("Switch PoE", "un", "Rede", "produto"),
                ("Cabo UTP Cat5e", "m", "Cabos e acessórios", "produto"),
                ("Caixa de proteção", "un", "Cabos e acessórios", "produto"),
            ]),
            ("Serviços", [
                ("Instalação de câmera", "un", "Serviços", "servico"),
                ("Configuração do sistema e acesso remoto", "un", "Serviços", "servico"),
            ]),
        ],
    },
    {
        "nome": "Alarme",
        "escopo": "Fornecimento e instalação de sistema de alarme.",
        "nao_incluso": "Obras civis, pontos elétricos e mensalidade de monitoramento.",
        "secoes": [
            ("Central", [
                ("Central de alarme", "un", "Alarme", "produto"),
                ("Bateria", "un", "Alarme", "produto"),
                ("Teclado", "un", "Alarme", "produto"),
            ]),
            ("Sensores", [
                ("Sensor de presença", "un", "Alarme", "produto"),
                ("Sensor de abertura", "un", "Alarme", "produto"),
            ]),
            ("Sinalização e comunicação", [
                ("Sirene", "un", "Alarme", "produto"),
                ("Módulo de comunicação", "un", "Alarme", "produto"),
            ]),
            ("Serviços", [
                ("Instalação e configuração do alarme", "un", "Serviços", "servico"),
            ]),
        ],
    },
    {
        "nome": "Equipamentos de TI",
        "escopo": "Fornecimento de equipamentos de TI.",
        "nao_incluso": "Migração de dados e treinamento de usuários.",
        "secoes": [
            ("Hardware", [
                ("Computador desktop", "un", "TI", "produto"),
                ("Notebook", "un", "TI", "produto"),
                ("Nobreak", "un", "TI", "produto"),
            ]),
            ("Licenças", [
                ("Licença de software", "un", "TI", "produto"),
            ]),
            ("Periféricos", [
                ("Monitor", "un", "TI", "produto"),
                ("Impressora", "un", "TI", "produto"),
            ]),
            ("Serviços", [
                ("Instalação e configuração de equipamento", "un", "Serviços", "servico"),
            ]),
        ],
    },
]
