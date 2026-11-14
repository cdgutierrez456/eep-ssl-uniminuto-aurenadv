# Evaluación del detector de EPP industrial

Pesos: `runs/epp/industria_n/weights/best.pt`. Generado por `python -m modulos.epp.entrenamiento.evaluar`.

## Resumen

| Conjunto | mAP50 | mAP50-95 | Precisión | Recall |
|---|---|---|---|---|
| Validación | 0.672 | 0.378 | 0.687 | 0.666 |
| Prueba | 0.695 | 0.385 | 0.692 | 0.697 |
| Primer plano (valid + test) | 0.718 | 0.410 | 0.726 | 0.710 |

## Validación

| Clase | Precisión | Recall | mAP50 | mAP50-95 |
|---|---|---|---|---|
| persona | 0.840 | 0.888 | 0.905 | 0.636 |
| casco | 0.834 | 0.897 | 0.906 | 0.523 |
| gafas | 0.654 | 0.570 | 0.573 | 0.243 |
| chaleco | 0.849 | 0.886 | 0.910 | 0.597 |
| sin_casco | 0.508 | 0.383 | 0.404 | 0.143 |
| sin_gafas | 0.434 | 0.369 | 0.334 | 0.126 |

Matriz de confusión: `runs/epp/evaluacion/valid/confusion_matrix.png`

## Prueba

| Clase | Precisión | Recall | mAP50 | mAP50-95 |
|---|---|---|---|---|
| persona | 0.849 | 0.909 | 0.926 | 0.649 |
| casco | 0.847 | 0.915 | 0.924 | 0.521 |
| gafas | 0.594 | 0.608 | 0.574 | 0.251 |
| chaleco | 0.862 | 0.870 | 0.906 | 0.584 |
| sin_casco | 0.599 | 0.443 | 0.481 | 0.176 |
| sin_gafas | 0.403 | 0.439 | 0.362 | 0.129 |

Matriz de confusión: `runs/epp/evaluacion/test/confusion_matrix.png`

## Primer plano (valid + test)

| Clase | Precisión | Recall | mAP50 | mAP50-95 |
|---|---|---|---|---|
| persona | 0.898 | 0.908 | 0.942 | 0.680 |
| casco | 0.873 | 0.933 | 0.938 | 0.560 |
| gafas | 0.651 | 0.621 | 0.619 | 0.270 |
| chaleco | 0.880 | 0.914 | 0.936 | 0.631 |
| sin_casco | 0.612 | 0.468 | 0.504 | 0.187 |
| sin_gafas | 0.442 | 0.414 | 0.365 | 0.134 |

Matriz de confusión: `runs/epp/evaluacion/primer_plano/confusion_matrix.png`
