"""DDS – Diálogo Diário de Segurança: biblioteca de temas, sugestão por ocorrências e geração do plano.

O diferencial do VigIA: o plano não é uma lista genérica. Os temas são escolhidos a partir das
ocorrências que as câmeras registraram no setor (ex.: muitas faltas de máscara → proteção
respiratória). Depois entram os temas menos usados no setor, alternando os assuntos.
"""

from collections import Counter
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Camera, DDSSession, DDSTheme, Event

CATEGORIES = [
    "EPI", "Máquinas e equipamentos", "Circulação e áreas", "Movimentação de cargas", "Trabalho em altura",
    "Eletricidade", "Espaço confinado", "Incêndio e emergência", "Produtos químicos", "Ergonomia e saúde",
    "Comportamento seguro", "Ordem e limpeza", "Meio ambiente",
]

# Temas de referência. "triggers": ocorrências do VigIA que tornam o tema prioritário.
# ppe:<item> = falta daquele EPI · type:<tipo> = tipo de ocorrência
THEMES = [
    # ---- EPI ----
    ("epi_uso_correto", "EPI", "Uso correto do EPI: quando, como e por quê", "NR-6", [
        "O EPI é a última barreira: só funciona se estiver no corpo, do jeito certo, o tempo todo.",
        "Cada área tem o seu EPI obrigatório – confira a sinalização na entrada do setor.",
        "EPI com defeito ou desconfortável: avise o líder e troque. Não improvise nem adapte.",
        "Dar o exemplo conta: corrija o colega com respeito quando ele estiver sem proteção.",
    ], "Em que momento do dia é mais fácil esquecer ou tirar o EPI? Como evitar?", ["type:ppe_missing"]),
    ("epi_capacete", "EPI", "Capacete: proteção da cabeça e ajuste da jugular", "NR-6", [
        "Protege contra queda de objetos, batidas em estruturas e choque elétrico (classe B).",
        "Ajuste a carneira ao tamanho da cabeça e use a jugular em altura ou em áreas com vento.",
        "Não use boné por baixo, não fure nem pinte o casco: isso reduz a resistência.",
        "Casco trincado, deformado ou que já sofreu impacto forte deve ser trocado.",
    ], "Onde no nosso setor existe risco de batida ou queda de objeto sobre a cabeça?", ["ppe:helmet"]),
    ("epi_oculos", "EPI", "Proteção dos olhos: partículas, respingos e radiação", "NR-6", [
        "Esmerilhamento, corte, solda e produtos químicos lançam partículas e respingos.",
        "Óculos sobre a testa ou pendurados no pescoço não protegem nada.",
        "Lente riscada ou embaçada atrapalha a visão: limpe ou troque.",
        "Respingo no olho: lave por 15 minutos no lava-olhos e procure o ambulatório.",
    ], "Quais tarefas aqui podem lançar algo nos olhos sem aviso?", ["ppe:glasses"]),
    ("epi_luvas", "EPI", "Luvas certas para cada risco", "NR-6", [
        "Existem luvas para corte, calor, produtos químicos e eletricidade – uma não substitui a outra.",
        "Perto de partes rotativas (furadeira, torno) luva pode ser puxada: siga o procedimento da máquina.",
        "Luva furada, rasgada ou encharcada de produto deve ser trocada na hora.",
        "Mãos são a parte do corpo mais atingida em acidentes na indústria.",
    ], "Qual luva usamos em cada tarefa do setor? Alguém tem dúvida?", ["ppe:gloves"]),
    ("epi_respiratoria", "EPI", "Proteção respiratória: vedação, filtro e guarda", "NR-6 · PPR", [
        "Poeiras, fumos de solda e vapores químicos causam doenças que aparecem só anos depois.",
        "Faça o teste de vedação toda vez que colocar: barba impede a vedação.",
        "Troque o filtro quando ficar difícil respirar ou sentir cheiro do produto.",
        "Guarde a máscara limpa e em saco fechado – nunca pendurada no pescoço na área.",
    ], "Em quais tarefas a máscara mais incomoda? O que podemos melhorar?", ["ppe:mask"]),
    ("epi_visibilidade", "EPI", "Colete refletivo e visibilidade nas áreas de circulação", "NR-6 · NR-11", [
        "Operador de empilhadeira e motorista têm pontos cegos: o colete faz você ser visto.",
        "Docas, pátios e corredores de carga exigem colete o tempo todo.",
        "Colete sujo ou desbotado perde o efeito refletivo: troque.",
        "Faça contato visual com o operador antes de passar perto do equipamento.",
    ], "Onde pedestres e veículos se cruzam no nosso setor?", ["ppe:vest"]),
    ("epi_auditiva", "EPI", "Protetor auricular: colocação correta e perda auditiva", "NR-6 · NR-15 Anexo 1", [
        "A perda auditiva por ruído é permanente e não dói: só se percebe tarde.",
        "Plug: enrole, puxe a orelha para cima e para trás, insira e segure até expandir.",
        "Tirar o protetor por poucos minutos em área ruidosa já reduz muito a proteção.",
        "A audiometria periódica acompanha a sua audição – não falte ao exame.",
    ], "Quais equipamentos do setor são mais barulhentos?", []),
    ("epi_conservacao", "EPI", "Conservação, higienização e troca do EPI (CA válido)", "NR-6", [
        "Todo EPI precisa de Certificado de Aprovação (CA) válido.",
        "Guarde em local limpo e seco; não deixe ao sol ou junto de produtos químicos.",
        "Higienize conforme o fabricante e não compartilhe protetor auricular nem máscara.",
        "A troca é gratuita: peça sempre que estiver danificado.",
    ], "Onde guardamos os EPIs no fim do turno? Está adequado?", []),
    # ---- Máquinas ----
    ("nr12_protecoes", "Máquinas e equipamentos", "Proteções de máquinas: nunca remover ou burlar", "NR-12", [
        "Grades, cortinas de luz e sensores existem para impedir o acesso à zona de perigo.",
        "Burlar sensor ou trabalhar com proteção aberta é a principal causa de amputações.",
        "Máquina com proteção danificada não opera: comunique e bloqueie.",
        "Só pessoas treinadas e autorizadas operam cada máquina.",
    ], "Já sentimos vontade de 'dar um jeitinho' numa proteção? Por quê?", ["type:restricted_zone"]),
    ("nr12_bloqueio", "Máquinas e equipamentos", "Bloqueio e etiquetagem (LOTO) antes de manutenção e limpeza",
     "NR-12 · NR-10", [
        "Desligar não é bloquear: alguém pode religar sem saber que você está na máquina.",
        "Cada pessoa coloca o seu cadeado e etiqueta; só quem colocou retira.",
        "Libere energias acumuladas: pneumática, hidráulica, molas e partes em movimento.",
        "Teste a partida com tudo bloqueado antes de começar o serviço.",
    ], "Em quais limpezas ou ajustes rápidos deixamos de bloquear?", ["type:restricted_zone"]),
    ("nr12_emergencia", "Máquinas e equipamentos", "Botões de emergência e partida segura", "NR-12", [
        "Saiba onde fica o botão de emergência de cada máquina que você opera ou passa perto.",
        "O botão deve estar livre, sinalizado e funcionando – teste conforme o checklist.",
        "Antes de dar partida, confira se ninguém está na zona de perigo.",
        "Depois de uma parada de emergência, investigue a causa antes de religar.",
    ], "Você alcança o botão de emergência da sua máquina em menos de 2 segundos?", []),
    # ---- Circulação e áreas ----
    ("area_restrita", "Circulação e áreas", "Áreas restritas e isolamento: respeite a sinalização", "NR-26 · NR-12", [
        "Faixas, correntes e placas marcam onde há risco de esmagamento, queda ou atropelamento.",
        "Entrar em área isolada sem autorização expõe você e quem está trabalhando lá.",
        "'Só vou buscar uma peça' é a frase mais comum antes de um acidente.",
        "As câmeras do VigIA registram entradas em zonas restritas para que possamos corrigir juntos.",
    ], "Por que as pessoas cortam caminho pelas áreas isoladas? Como resolver?", ["type:restricted_zone"]),
    ("circulacao", "Circulação e áreas", "Circulação segura: faixas de pedestres e cruzamento com veículos",
     "NR-11 · NR-12", [
        "Ande pelas faixas de pedestres, mesmo que o caminho fique mais longo.",
        "Pare nos cruzamentos, olhe para os dois lados e espere o veículo passar.",
        "Não use celular andando em área de circulação de empilhadeiras.",
        "Mantenha corredores e rotas desobstruídos.",
    ], "Quais cruzamentos do setor são mais perigosos?", ["type:restricted_zone", "type:max_people"]),
    ("lotacao", "Circulação e áreas", "Lotação de áreas e postos: por que existe limite de pessoas", "NR-12 · NR-23", [
        "Pessoas demais perto de uma máquina ou carga aumentam o risco de esmagamento.",
        "O limite também garante saída rápida numa emergência.",
        "Quem não está na tarefa deve aguardar fora da área demarcada.",
        "Visitas e terceiros só entram acompanhados e com os EPIs da área.",
    ], "Em que situações juntamos gente demais no mesmo ponto?", ["type:max_people"]),
    # ---- Movimentação de cargas ----
    ("empilhadeira", "Movimentação de cargas", "Empilhadeira: inspeção pré-uso, velocidade e carga", "NR-11", [
        "Só opera quem tem treinamento e autorização vigentes (crachá de operador).",
        "Faça o checklist antes do turno: freio, buzina, luzes, garfos e vazamentos.",
        "Respeite a capacidade e transporte a carga baixa; em rampa, carga voltada para cima.",
        "Nunca transporte pessoas nos garfos ou eleve alguém sem plataforma própria.",
    ], "O checklist da empilhadeira é feito de verdade ou só assinado?", ["ppe:vest", "type:restricted_zone"]),
    ("levantamento_manual", "Movimentação de cargas", "Levantamento manual de cargas: postura e limites", "NR-17", [
        "Dobre os joelhos, mantenha as costas retas e a carga junto ao corpo.",
        "Não gire o tronco com peso: vire o corpo com os pés.",
        "Carga pesada ou desajeitada: peça ajuda ou use carrinho e talha.",
        "Dor nas costas recorrente deve ser comunicada ao ambulatório.",
    ], "Quais cargas do setor deveriam ter um auxílio mecânico?", []),
    ("ponte_rolante", "Movimentação de cargas", "Ponte rolante e içamento: nunca fique sob a carga", "NR-11 · NR-12", [
        "Inspecione cintas, correntes e ganchos antes de cada uso; descarte o que estiver danificado.",
        "Ninguém passa ou permanece sob carga suspensa.",
        "Use cabo-guia para conduzir a carga, nunca as mãos.",
        "Combine os sinais com o operador antes de começar.",
    ], "Onde as pessoas costumam passar sob cargas içadas?", ["type:restricted_zone"]),
    # ---- Altura ----
    ("altura_cinto", "Trabalho em altura", "Trabalho em altura: cinto paraquedista e ancoragem", "NR-35", [
        "Acima de 2 m com risco de queda é trabalho em altura: exige treinamento e ASO apto.",
        "Ancore o talabarte em ponto resistente, acima da cabeça, antes de se expor ao risco.",
        "Inspecione o cinto antes do uso: costuras, fivelas e absorvedor de energia.",
        "Sem permissão de trabalho e análise de risco, o serviço não começa.",
    ], "Que tarefas 'rápidas' em altura fazemos sem ancoragem?", []),
    ("escadas", "Trabalho em altura", "Escadas portáteis: inspeção e três pontos de apoio", "NR-35 · NR-18", [
        "Inspecione degraus, sapatas e travas antes de subir.",
        "Mantenha três pontos de contato: duas mãos e um pé, ou dois pés e uma mão.",
        "Não use o último degrau e não estique o corpo para fora da escada.",
        "Escada improvisada (caixa, cadeira, palete) é proibida.",
    ], "Onde as escadas ficam guardadas e quem confere o estado delas?", []),
    # ---- Eletricidade ----
    ("eletricidade", "Eletricidade", "Riscos elétricos: só profissional autorizado mexe", "NR-10", [
        "Painéis e instalações elétricas só podem ser abertos por profissional autorizado (NR-10).",
        "Choque elétrico pode matar mesmo em baixa tensão; arco elétrico causa queimaduras graves.",
        "Painel aberto, cabo descascado ou cheiro de queimado: isole a área e comunique.",
        "Nunca use água para apagar fogo em equipamento elétrico.",
    ], "Existe algum painel ou cabo no setor que precisa de reparo?", []),
    ("extensoes", "Eletricidade", "Extensões, tomadas e gambiarras", "NR-10 · NR-23", [
        "Benjamins e extensões emendadas sobrecarregam a instalação e causam incêndios.",
        "Cabos não podem passar por áreas de trânsito de veículos ou ficar sobre poças.",
        "Plugue danificado ou adaptado deve ser substituído por eletricista.",
        "Desligue equipamentos portáteis da tomada ao final do uso.",
    ], "Onde existe gambiarra elétrica no setor hoje?", ["type:fire_smoke"]),
    # ---- Espaço confinado ----
    ("confinado", "Espaço confinado", "Espaço confinado: permissão de entrada e vigia", "NR-33", [
        "Tanques, silos, galerias e poços podem ter falta de oxigênio ou gases tóxicos sem cheiro.",
        "Entrada só com Permissão de Entrada e Trabalho (PET), medição de gases e vigia do lado de fora.",
        "Metade das mortes em espaço confinado é de quem entrou para socorrer: não entre sem equipamento.",
        "Trabalhador e vigia precisam de treinamento e ASO com aptidão para espaço confinado.",
    ], "Quais espaços do nosso setor são confinados? Estão sinalizados?", []),
    # ---- Incêndio e emergência ----
    ("incendio_prevencao", "Incêndio e emergência", "Prevenção de incêndio: fontes de ignição e inflamáveis", "NR-23", [
        "Fogo precisa de combustível, oxigênio e calor: tire um deles e o fogo não começa.",
        "Inflamáveis ficam em local ventilado, identificado e longe de faíscas e calor.",
        "Estopa e panos com óleo devem ir para recipiente metálico com tampa.",
        "Fumar só nas áreas permitidas.",
    ], "O que no nosso setor poderia começar um incêndio?", ["type:fire_smoke"]),
    ("extintores", "Incêndio e emergência", "Extintores: classes de fogo e como usar", "NR-23", [
        "Classe A: papel e madeira · B: líquidos inflamáveis · C: equipamento elétrico energizado.",
        "Uso: puxe o pino, aponte para a base do fogo, aperte o gatilho e varra de um lado ao outro.",
        "Extintores e hidrantes devem ficar desobstruídos e sinalizados.",
        "Fogo que não apaga em poucos segundos: saia, acione o alarme e a brigada.",
    ], "Onde está o extintor mais próximo do seu posto? Qual a classe?", ["type:fire_smoke"]),
    ("emergencia_rotas", "Incêndio e emergência", "Plano de emergência: rotas de fuga e ponto de encontro", "NR-23", [
        "Conheça duas rotas de saída a partir do seu posto.",
        "Portas e saídas de emergência nunca podem ficar trancadas ou bloqueadas.",
        "Ao ouvir o alarme, pare as máquinas com segurança e siga para o ponto de encontro.",
        "Não volte para buscar objetos; avise a brigada se alguém estiver faltando.",
    ], "Onde é o nosso ponto de encontro? Todos sabem chegar lá?", ["type:fire_smoke"]),
    ("trabalho_quente", "Incêndio e emergência", "Trabalho a quente: permissão, área limpa e vigia de fogo",
     "NR-23 · procedimento interno", [
        "Solda, corte e esmerilhamento fora da área de solda exigem permissão de trabalho.",
        "Retire ou proteja materiais combustíveis num raio de pelo menos 10 metros.",
        "Mantenha extintor ao lado e vigia de fogo durante e após o serviço.",
        "Fagulhas podem ficar incandescentes por até uma hora: inspecione antes de liberar a área.",
    ], "Quando foi a última vez que fizemos trabalho a quente fora da área de solda?", ["type:fire_smoke"]),
    # ---- Químicos ----
    ("quimicos_fds", "Produtos químicos", "Produtos químicos: rótulo, FDS e armazenamento", "NR-26 · GHS", [
        "Leia o rótulo e a Ficha com Dados de Segurança (FDS) antes de usar um produto novo.",
        "Nunca transfira produto para garrafa de bebida ou recipiente sem identificação.",
        "Produtos incompatíveis (ácidos e bases, oxidantes e inflamáveis) ficam separados.",
        "Derramamento: isole, use o kit de emergência e comunique.",
    ], "Sabemos onde estão as FDS dos produtos que usamos?", ["ppe:mask", "ppe:gloves", "ppe:glasses"]),
    # ---- Ergonomia e saúde ----
    ("ergonomia_posto", "Ergonomia e saúde", "Ergonomia no posto: pausas, postura e alongamento", "NR-17", [
        "Ajuste a altura da bancada, da cadeira e da tela ao seu corpo.",
        "Movimentos repetitivos pedem pausas curtas e alternância de tarefas.",
        "Alongar antes e durante o turno reduz dores e lesões.",
        "Formigamento ou dor persistente nas mãos e braços: procure o ambulatório cedo.",
    ], "Qual tarefa do setor mais cansa ou dói? O que podemos ajustar?", []),
    ("fadiga", "Ergonomia e saúde", "Fadiga e sono: atenção no início e no fim do turno", "NR-1 · NR-17", [
        "Cansaço reduz a atenção tanto quanto álcool: os acidentes aumentam no fim do turno.",
        "Durma bem antes de turnos noturnos e evite trocar o sono por horas extras seguidas.",
        "Sentiu sono operando máquina ou veículo: pare e avise o líder.",
        "Atenção redobrada nas trocas de turno: passe as informações completas.",
    ], "Em que horário do turno sentimos mais cansaço?", []),
    ("calor_hidratacao", "Ergonomia e saúde", "Calor e hidratação", "NR-15 Anexo 3 · NR-9", [
        "Em ambientes quentes beba água a cada 15–20 minutos, mesmo sem sede.",
        "Tontura, dor de cabeça e câimbras são sinais de alerta: pare e procure sombra.",
        "Respeite as pausas de recuperação térmica.",
        "Evite refeições pesadas e bebidas alcoólicas antes do turno em dias quentes.",
    ], "Há bebedouros suficientes e próximos dos postos mais quentes?", []),
    ("saude_mental", "Ergonomia e saúde", "Saúde mental e pedir ajuda", "NR-1 · riscos psicossociais", [
        "Estresse, preocupação e pressão afetam a atenção e aumentam o risco de acidentes.",
        "Conversar com o líder, com o RH ou com o ambulatório é sinal de responsabilidade, não de fraqueza.",
        "Respeito e cooperação na equipe também são segurança.",
        "Assédio e intimidação devem ser comunicados pelos canais da empresa.",
    ], "O que torna o nosso dia de trabalho mais pesado do que precisaria ser?", []),
    # ---- Comportamento seguro ----
    ("quase_acidente", "Comportamento seguro", "Quase acidente: por que relatar", "NR-1 · GRO", [
        "Para cada acidente grave existem dezenas de quase acidentes que avisaram antes.",
        "Relatar não é dedurar: é corrigir a condição antes que alguém se machuque.",
        "Descreva o que aconteceu, onde e o que poderia ter acontecido.",
        "As ocorrências do VigIA servem ao mesmo propósito: aprender e corrigir, não punir.",
    ], "Qual quase acidente você presenciou recentemente?", ["type:restricted_zone", "type:ppe_missing"]),
    ("atalhos", "Comportamento seguro", "Pressa e atalhos: o risco do 'só desta vez'", "NR-1", [
        "A maioria dos acidentes acontece em tarefas conhecidas, feitas com pressa.",
        "Atalho que economiza um minuto pode custar uma mão.",
        "Se o procedimento atrapalha a produção, discuta com o líder em vez de pular etapas.",
        "Parar para fazer certo é sempre permitido.",
    ], "Quais atalhos viraram costume no setor?", ["type:restricted_zone", "type:ppe_missing"]),
    ("celular", "Comportamento seguro", "Uso de celular em áreas operacionais", "Procedimento interno", [
        "Celular desvia a atenção de máquinas, veículos e cargas em movimento.",
        "Use apenas nas áreas permitidas ou parado em local seguro.",
        "Fotos e vídeos dentro da fábrica seguem as regras de sigilo da empresa.",
        "Fones de ouvido impedem ouvir alarmes e buzinas.",
    ], "Em quais momentos o celular mais distrai no setor?", []),
    ("recusa", "Comportamento seguro", "Direito de recusa: parar quando há risco grave e iminente", "NR-1 (item 1.4.3)", [
        "Todo trabalhador pode interromper uma atividade quando houver risco grave e iminente.",
        "Comunique imediatamente o líder, que deve avaliar e corrigir a situação.",
        "Ninguém pode ser punido por exercer o direito de recusa de boa-fé.",
        "Segurança é responsabilidade de todos, não só do SESMT.",
    ], "Você se sentiria à vontade para parar uma tarefa perigosa? O que impede?", []),
    # ---- Ordem e limpeza ----
    ("5s", "Ordem e limpeza", "Ordem e limpeza (5S): tropeços, quedas e acesso às emergências", "NR-12 · NR-23", [
        "Escorregões e tropeços estão entre os acidentes mais comuns na indústria.",
        "Óleo e água no piso: sinalize e limpe na hora.",
        "Cada coisa no seu lugar: ferramentas guardadas, corredores livres.",
        "Extintores, hidrantes, painéis e saídas de emergência sempre desobstruídos.",
    ], "O que está fora do lugar no setor agora?", ["type:max_people"]),
    # ---- Meio ambiente ----
    ("residuos", "Meio ambiente", "Descarte correto de resíduos e coleta seletiva", "Política ambiental", [
        "Resíduos contaminados com óleo ou químicos têm descarte próprio, nunca no lixo comum.",
        "Separe recicláveis conforme as cores dos coletores.",
        "Vazamentos para o solo ou ralo devem ser contidos e comunicados.",
        "Reduzir o desperdício também reduz custos e riscos.",
    ], "Onde descartamos os resíduos contaminados do setor?", []),
]

THEME_INDEX = {t[0]: t for t in THEMES}

PPE_WORDS = {"capacete": "helmet", "colete": "vest", "óculos": "glasses", "oculos": "glasses",
             "luva": "gloves", "máscara": "mask", "mascara": "mask"}


def ensure_themes(db: Session) -> int:
    """Cria os temas de referência que ainda não existem (instalação nova ou versão nova)."""
    existing = set(db.scalars(select(DDSTheme.code).where(DDSTheme.code.is_not(None))))
    added = 0
    for code, category, title, reference, points, question, triggers in THEMES:
        if code in existing:
            continue
        db.add(DDSTheme(code=code, category=category, title=title, reference=reference, points=points,
                        question=question, triggers=triggers, builtin=True))
        added += 1
    if added:
        db.commit()
    return added


def event_tags(event: Event) -> list[str]:
    tags = [f"type:{event.type}"]
    if event.type == "ppe_missing":
        msg = (event.message or "").lower()
        tags += [f"ppe:{item}" for word, item in PPE_WORDS.items() if word in msg]
    return tags


def suggestions(db: Session, unit_id: int | None, sector_id: int | None, days: int = 30) -> list[dict]:
    """Temas prioritários pelas ocorrências recentes (descartadas não contam)."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    cams = select(Camera.id)
    if sector_id is not None:
        cams = cams.where(Camera.sector_id == sector_id)
    elif unit_id is not None:
        cams = cams.where(Camera.unit_id == unit_id)
    events = db.scalars(select(Event).where(Event.created_at >= since, Event.status != "descartada",
                                            Event.camera_id.in_(cams))).all()
    tags = Counter(tag for e in events for tag in event_tags(e))
    if not tags:
        return []
    labels = {"type:ppe_missing": "falta de EPI", "type:restricted_zone": "entrada em zona restrita",
              "type:max_people": "excesso de pessoas", "type:fire_smoke": "fogo/fumaça",
              "ppe:helmet": "falta de capacete", "ppe:vest": "falta de colete", "ppe:glasses": "falta de óculos",
              "ppe:gloves": "falta de luvas", "ppe:mask": "falta de máscara"}
    out = []
    for theme in db.scalars(select(DDSTheme).where(DDSTheme.active.is_(True))):
        hits = {t: tags[t] for t in (theme.triggers or []) if tags.get(t)}
        if not hits:
            continue
        # EPI específico pesa mais que o genérico
        score = sum(n * (2 if t.startswith("ppe:") else 1) for t, n in hits.items())
        main = max(hits, key=lambda t: (hits[t] * (2 if t.startswith("ppe:") else 1)))
        out.append({"theme_id": theme.id, "title": theme.title, "category": theme.category, "score": score,
                    "reason": f"{hits[main]} ocorrência(s) de {labels.get(main, main)} nos últimos {days} dias"})
    return sorted(out, key=lambda s: -s["score"])


def generate_plan(db: Session, unit_id: int, sector_id: int | None, shift: str, start: date, end: date,
                  weekdays: list[int], facilitator: str) -> list[dict]:
    """Datas do período × temas: primeiro os sugeridos pelas ocorrências, depois os menos usados
    no setor, alternando assuntos. Não repete tema no mesmo plano nem duplica DDS já marcado."""
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    days = [d for d in days if d.weekday() in weekdays]
    taken = set(db.scalars(select(DDSSession.day).where(
        DDSSession.unit_id == unit_id, DDSSession.sector_id.is_(sector_id) if sector_id is None
        else DDSSession.sector_id == sector_id, DDSSession.shift == shift, DDSSession.status != "cancelado",
        DDSSession.day >= start, DDSSession.day <= end)))
    days = [d for d in days if d not in taken]
    if not days:
        return []

    themes = {t.id: t for t in db.scalars(select(DDSTheme).where(DDSTheme.active.is_(True)))}
    last_q = select(DDSSession.theme_id, func.max(DDSSession.day)).where(
        DDSSession.unit_id == unit_id, DDSSession.status != "cancelado").group_by(DDSSession.theme_id)
    if sector_id is not None:
        last_q = last_q.where(DDSSession.sector_id == sector_id)
    last_used = dict(db.execute(last_q).all())

    queue: list[tuple[int, str]] = []
    recent = start - timedelta(days=45)
    for s in suggestions(db, unit_id, sector_id):
        used = last_used.get(s["theme_id"])
        if used is None or used < recent:  # tema sugerido já dado há pouco: espera a rotação
            queue.append((s["theme_id"], s["reason"]))
    # rotação: menos usados primeiro, intercalando as categorias
    by_cat: dict[str, list] = {}
    for t in sorted(themes.values(), key=lambda t: (last_used.get(t.id) or date.min, t.id)):
        if t.id not in {q[0] for q in queue}:
            by_cat.setdefault(t.category, []).append(t)
    cats = sorted(by_cat, key=lambda c: (last_used.get(by_cat[c][0].id) or date.min, CATEGORIES.index(c)
                                         if c in CATEGORIES else 99))
    while any(by_cat.values()):
        for c in cats:
            if by_cat[c]:
                queue.append((by_cat[c].pop(0).id, ""))
    plan = []
    for i, d in enumerate(days):
        theme_id, reason = queue[i % len(queue)]
        t = themes[theme_id]
        plan.append({"date": d, "theme_id": t.id, "title": t.title, "category": t.category,
                     "reason": reason or "rotação de temas", "shift": shift, "facilitator": facilitator})
    return plan
