# Modelos de IA do VigIA

Configure no `.env` quais modelos o detector usa (separados por vírgula):

```
MODEL_PATHS=modelos/yolox_s.onnx,modelos/epi.onnx
```

| Tipo de arquivo | Motor | Licença do motor | Uso comercial |
|---|---|---|---|
| `.onnx` + `.json` | ONNX Runtime | MIT | Livre (confira a licença de quem treinou o modelo) |
| `.pt` | Ultralytics YOLO | AGPL-3.0 | Exige a Enterprise License da Ultralytics (ou abrir todo o código) |

Com **apenas modelos `.onnx`**, o `iniciar.bat` e o `iniciar_planta.bat` não instalam a Ultralytics.
Em um computador que já tem a Ultralytics, crie o ambiente de novo (apague a pasta `.venv`) para a
versão comercial não levar a dependência AGPL.

## Caminho livre (sem AGPL), passo a passo

### 1. Pessoas – modelo COCO pronto (YOLOX, Apache-2.0)

Baixe o `yolox_s.onnx` na página de versões do [YOLOX](https://github.com/Megvii-BaseDetection/YOLOX)
(seção ONNXRuntime da demonstração), salve em `modelos/` e crie a ficha dele:

```
cd detector
python -m vigia_detector.dataset criar-meta --modelo ..\modelos\yolox_s.onnx --formato yolox --classes coco --licenca Apache-2.0 --origem "YOLOX oficial (COCO)"
```

### 2. EPI – treinar com as suas imagens

1. Colete e corrija as imagens (veja o README: `DATASET_DIR`, `importar`, Label Studio).
2. Prepare e converta para COCO:

   ```
   python -m vigia_detector.dataset preparar --origem C:\vigia-treino\coleta --saida C:\vigia-treino\conjunto
   python -m vigia_detector.dataset exportar-coco --dados C:\vigia-treino\conjunto --saida C:\vigia-treino\coco
   ```

3. Treine no **YOLOX** ou no **D-FINE** (ambos Apache-2.0) usando a pasta `coco` (`num_classes` = número de
   classes mostrado pelo comando acima). Exporte para ONNX com a ferramenta de cada projeto:
   - YOLOX: `tools/export_onnx.py` → formato `yolox`
   - D-FINE / RT-DETR: `tools/deployment/export_onnx.py` → formato `detr`
4. Copie para `modelos/epi.onnx` e crie a ficha:

   ```
   python -m vigia_detector.dataset criar-meta --modelo ..\modelos\epi.onnx --formato yolox --classes C:\vigia-treino\coco\classes.json --licenca Apache-2.0 --origem "treinado com YOLOX sobre imagens das câmeras"
   ```

5. Ajuste o `MODEL_PATHS` e reinicie. A janela do detector lista cada modelo com a licença declarada.

O treino em GPU é muito mais rápido (um computador com placa NVIDIA ou uma máquina na nuvem por algumas horas).
