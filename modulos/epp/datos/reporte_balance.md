# Balance del dataset de EPP industrial

Generado por `python -m modulos.epp.datos.preparar_dataset`. No editar a mano.

Imágenes: 12824 (train 10262, valid 1284, test 1278). Primer plano en valid+test: 2088.

## Fuentes

| Fuente | Licencia | Leídas | Sin etiquetas útiles | Duplicadas | Personas completadas | Usadas |
|---|---|---|---|---|---|---|
| machine-iimx4/ppe-detection-vvyxs | CC BY 4.0 | 4349 | 15 | 719 | 0 | 3603 |
| a13/ppe-1-5g9zq | CC BY 4.0 | 1918 | 354 | 592 | 1833 | 972 |
| chandimas-workspace/construction-safety-monitor-mlpd4 | CC BY 4.0 | 12424 | 281 | 6352 | 15780 | 5791 |
| object-detection-mygq1/ppe-x5hms | CC BY 4.0 | 3337 | 34 | 845 | 0 | 2458 |

## Instancias por clase

| Clase | train | valid | test | Imágenes en train | Tamaño mediano |
|---|---|---|---|---|---|
| persona | 17404 | 2139 | 2163 | 9346 | 0.70 del alto |
| casco | 13805 | 1655 | 1696 | 7716 | 0.12 del ancho |
| gafas | 2884 | 337 | 370 | 2331 | 0.14 del ancho |
| chaleco | 11173 | 1448 | 1391 | 6987 | 0.22 del ancho |
| sin_casco | 3249 | 475 | 463 | 1818 | 0.12 del ancho |
| sin_gafas | 3595 | 379 | 396 | 2175 | 0.09 del ancho |

## Clases quitadas

- `proteccion_auditiva`: 393 instancias en train (mínimo 400).

## Lectura

- «Tamaño mediano» es la fracción de la imagen que ocupa la caja: en el stand (1-2 m) la persona ocupa 0.6 o más del alto.
- Los duplicados se detectan por pHash; las copias aumentadas de una misma imagen quedan en el mismo split.
- Las fuentes con licencia CC BY 4.0 exigen atribución a sus autores.
