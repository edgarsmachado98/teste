# Acessar a Carteira de Aportes fora de casa (Tailscale)

O app continua rodando no seu computador. O Tailscale cria uma rede privada entre o computador e os
celulares de vocês: fora de casa, o celular abre o app como se estivesse no Wi-Fi de casa, com endereço
**https** (cadeado). Só os aparelhos ligados à sua conta do Tailscale conseguem abrir; ninguém mais na
internet vê o app. Não precisa mexer no roteador e o plano pessoal é gratuito.

Bônus do https: a **câmera ao vivo** do leitor de QR Code da nota fiscal passa a funcionar no celular.

---

## 1. Criar a conta

1. Acesse **tailscale.com** e clique em **Get started**.
2. Entre com sua conta Google (ou Microsoft/Apple). Essa será a conta da família.

## 2. Instalar no computador onde o app roda

1. Baixe em **tailscale.com/download** a versão para Windows e instale.
2. Ao terminar, aparece o ícone do Tailscale perto do relógio. Clique nele → **Log in** e entre com a
   mesma conta do passo 1.
3. Pronto: o computador aparece em **login.tailscale.com/admin/machines**. Anote o nome dele
   (ex.: `pc-edgar`). Se quiser um nome mais fácil, clique nos três pontinhos → **Edit machine name**.

## 3. Instalar nos celulares

1. Instale o app **Tailscale** (Play Store ou App Store) no seu celular e no da Eliandra.
2. Entre com a **mesma conta** do passo 1 e permita a criação da VPN quando o celular pedir.
3. Deixe o Tailscale **ligado** (no Android aparece o ícone de chave na barra de cima).

> Prefere que a Eliandra use a própria conta? No painel (login.tailscale.com) vá em **Users → Invite users**
> e convide o e-mail dela. O plano gratuito aceita até 3 usuários.

## 4. Ligar o https (uma vez só)

1. Abra **login.tailscale.com/admin/dns**.
2. Confira se **MagicDNS** está ativado (normalmente já vem ligado).
3. Mais abaixo, em **HTTPS Certificates**, clique em **Enable HTTPS**.

## 5. Publicar o app na rede privada (uma vez só)

Com o app aberto (`python app.py`), abra o **Prompt de Comando** no computador e digite:

```
tailscale serve --bg 5000
```

> Se aparecer **"O termo 'tailscale' não é reconhecido"**, use o caminho completo (no PowerShell, com o `&`
> na frente):
>
> ```
> & "C:\Program Files\Tailscale\tailscale.exe" serve --bg 5000
> ```
>
> No Prompt de Comando (cmd) é o mesmo sem o `&`. Fechar e abrir o PowerShell depois de instalar também
> costuma resolver.

Ele responde com o endereço do app, algo como:

```
https://pc-edgar.tail1234.ts.net/
|-- proxy http://127.0.0.1:5000
```

Esse é o endereço para usar fora de casa. A configuração fica salva: mesmo depois de reiniciar o
computador, não precisa digitar de novo. Se aparecer uma mensagem pedindo para habilitar o recurso,
abra o link que ela mostra, confirme e rode o comando de novo.

O próprio app também mostra esse endereço ao iniciar, na janela preta, na linha **Fora de casa**.

## 6. Abrir no celular

1. Com o Tailscale ligado no celular, abra no navegador o endereço do passo 5
   (ex.: `https://pc-edgar.tail1234.ts.net`). O primeiro acesso pode levar alguns segundos.
2. Faça o login normal do app.
3. Dica: no menu do navegador, toque em **Adicionar à tela inicial**. O app ganha um ícone como se fosse
   instalado.

Funciona tanto fora de casa (4G ou outro Wi-Fi) quanto em casa. Pode usar só esse endereço sempre.

## 7. Deixar o computador pronto

O app só responde enquanto o computador está **ligado** e o `python app.py` está **aberto**.

- **Não deixar o computador dormir:** Configurações do Windows → Sistema → Energia → em
  "Quando conectado, colocar o dispositivo em suspensão após", escolha **Nunca**.
- **Abrir o app junto com o Windows:**
  1. Aperte **Windows + R**, digite `shell:startup` e Enter. Abre a pasta Inicializar.
  2. Na pasta do sistema, clique com o botão direito em **iniciar_carteira.bat** →
     **Mostrar mais opções** → **Criar atalho**.
  3. Arraste o atalho criado para a pasta Inicializar.
- O Tailscale do computador já inicia sozinho com o Windows.

---

## Se não abrir

| O que acontece | O que fazer |
|---|---|
| A página não carrega no celular | Confira se o Tailscale está ligado no celular (ícone de chave) e no computador. |
| Carregava e parou | O computador dormiu ou a janela do `python app.py` foi fechada. Abra de novo. |
| "Este site não pode ser acessado" logo após o passo 5 | Aguarde um minuto (o certificado https está sendo emitido) e tente de novo. |
| O comando `tailscale` não é reconhecido | Use o caminho completo: `& "C:\Program Files\Tailscale\tailscale.exe" serve --bg 5000` (veja o passo 5). Se o arquivo não existir, o Tailscale não foi instalado: refaça o passo 2. |
| Câmera do QR Code não abre | Use o endereço **https://...ts.net**, não o `http://192.168...`. |

## Desligar o acesso remoto

No Prompt de Comando do computador:

```
tailscale serve reset
```

(ou `& "C:\Program Files\Tailscale\tailscale.exe" serve reset`, se o comando curto não for reconhecido)

Para tirar um celular (perdido ou trocado): login.tailscale.com/admin/machines → três pontinhos →
**Remove**.

## Segurança

- Use o **`tailscale serve`** (rede privada). **Não** use o `tailscale funnel`: ele publica o app na
  internet para qualquer pessoa.
- Não abra a porta 5000 no roteador.
- O login e a senha do app continuam valendo; o Tailscale é uma proteção a mais por fora.
