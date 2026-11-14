"""Prepara el dataset de EPP industrial de forma reproducible.

Pasos: descarga (Roboflow) -> mapeo explícito de clases (fuentes.yaml) -> completar la
clase persona -> fusión -> deduplicación -> partición -> data.yaml + reporte de balance.

Uso::

    python -m modulos.epp.datos.preparar_dataset
    python -m modulos.epp.datos.preparar_dataset --local datos_propios/stand_01

La descarga necesita ROBOFLOW_API_KEY en el .env. Lo ya descargado no se vuelve a bajar.
Salida: datasets/epp_industria/ (fuera de git) y modulos/epp/datos/reporte_balance.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import find_dotenv, load_dotenv

RAIZ = Path(__file__).resolve().parents[3]
RUTA_FUENTES = Path(__file__).with_name("fuentes.yaml")
RUTA_REPORTE = Path(__file__).with_name("reporte_balance.md")
DIR_DATASETS = RAIZ / "datasets"
DIR_DESCARGAS = DIR_DATASETS / "descargas"
DIR_SALIDA = DIR_DATASETS / "epp_industria"
DIR_MODELOS = RAIZ / "modulos" / "epp" / "modelos"
EXTENSIONES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
OBLIGATORIAS = ("persona", "casco", "gafas")
MARCA_COMPLETO = ".descarga_completa"

Etiqueta = tuple[str, float, float, float, float]  # (clase canónica, cx, cy, ancho, alto) en 0-1


@dataclass
class Muestra:
    """Una imagen con sus etiquetas ya en clases canónicas."""

    fuente: str
    ruta: Path
    etiquetas: list[Etiqueta]
    phash: int = 0
    split: str = ""


@dataclass
class Fuente:
    """Una fuente de datos y sus contadores para el reporte."""

    nombre: str
    licencia: str
    muestras: list[Muestra] = field(default_factory=list)
    leidas: int = 0
    sin_etiquetas: int = 0
    personas_completadas: int = 0
    duplicadas: int = 0


def normalizar(nombre: str) -> str:
    """Nombre de clase sin mayúsculas, espacios, guiones ni guiones bajos."""
    return re.sub(r"[\s_\-]+", "", str(nombre)).lower()


# ------------------------------------------------------------------ descarga

def descargar(slug: str, version: int, formato: str) -> Path:
    """Baja una versión de Roboflow Universe en formato YOLO (si no está ya en disco)."""
    destino = DIR_DESCARGAS / f"{slug.replace('/', '__')}__v{version}"
    if (destino / MARCA_COMPLETO).exists():
        print(f"  {slug} v{version}: ya descargado")
        return destino
    if destino.exists():
        shutil.rmtree(destino)  # descarga anterior incompleta
    clave = os.getenv("ROBOFLOW_API_KEY")
    if not clave:
        sys.exit(
            "Falta ROBOFLOW_API_KEY. Agrégala al archivo .env de la raíz del repo "
            "(se obtiene en app.roboflow.com > Settings > API Keys) y vuelve a correr."
        )
    # Se usa la API REST de Roboflow directamente (no su SDK, que fuerza otra versión de OpenCV).
    import zipfile

    import httpx

    print(f"  {slug} v{version}: pidiendo la exportación…")
    respuesta = httpx.get(
        f"https://api.roboflow.com/{slug}/{version}/{formato}", params={"api_key": clave}, timeout=120
    )
    if respuesta.status_code != 200:
        sys.exit(f"Roboflow respondió {respuesta.status_code} para {slug} v{version}: {respuesta.text[:300]}")
    enlace = respuesta.json().get("export", {}).get("link")
    if not enlace:
        sys.exit(f"Roboflow no devolvió un enlace de descarga para {slug} v{version} en formato {formato}")

    destino.mkdir(parents=True, exist_ok=True)
    ruta_zip = destino / "descarga.zip"
    with httpx.stream("GET", enlace, timeout=600, follow_redirects=True) as descarga:
        descarga.raise_for_status()
        with open(ruta_zip, "wb") as archivo:
            for bloque in descarga.iter_bytes(1 << 20):
                archivo.write(bloque)
    print(f"  {slug} v{version}: {ruta_zip.stat().st_size / 1e6:.0f} MB, descomprimiendo…")
    with zipfile.ZipFile(ruta_zip) as comprimido:
        for miembro in comprimido.infolist():
            if miembro.is_dir():
                continue
            relativa = Path(miembro.filename)
            if ".." in relativa.parts or relativa.is_absolute():
                continue
            salida = destino / relativa.with_name(_nombre_corto(relativa.name))
            salida.parent.mkdir(parents=True, exist_ok=True)
            with comprimido.open(miembro) as origen, open(salida, "wb") as archivo:
                shutil.copyfileobj(origen, archivo)
    ruta_zip.unlink()
    (destino / MARCA_COMPLETO).write_text("ok", encoding="utf-8")
    return destino


def _nombre_corto(nombre: str, maximo: int = 60) -> str:
    """Acorta nombres de archivo muy largos (Windows limita la ruta a 260 caracteres).

    Conserva el sufijo ".rf.<hash>.<ext>" de Roboflow y reemplaza el exceso del nombre
    original por un hash corto, de modo que la imagen y su etiqueta sigan emparejadas y
    las copias aumentadas de una misma imagen sigan compartiendo el prefijo.
    """
    original, separador, resto = nombre.partition(".rf.")
    if not separador:
        original, resto = Path(nombre).stem, Path(nombre).suffix.lstrip(".")
        separador = "."
    if len(original) <= maximo:
        return nombre
    corto = original[:maximo] + "~" + hashlib.md5(original.encode("utf-8")).hexdigest()[:8]
    return corto + separador + resto


# ------------------------------------------------------------------- lectura

def leer_etiquetas_yolo(ruta: Path) -> list[tuple[int, float, float, float, float]]:
    """Lee un .txt YOLO. Los polígonos se convierten a su caja envolvente."""
    etiquetas = []
    if not ruta.exists():
        return etiquetas
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        partes = linea.split()
        if len(partes) < 5:
            continue
        try:
            indice = int(float(partes[0]))
            valores = [float(v) for v in partes[1:]]
        except ValueError:
            continue
        if len(valores) == 4:
            cx, cy, ancho, alto = valores
            x1, y1, x2, y2 = cx - ancho / 2, cy - alto / 2, cx + ancho / 2, cy + alto / 2
        else:
            xs, ys = valores[0::2], valores[1::2]
            x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
        x1, y1, x2, y2 = (min(1.0, max(0.0, v)) for v in (x1, y1, x2, y2))
        if x2 - x1 <= 0 or y2 - y1 <= 0:
            continue
        etiquetas.append((indice, (x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1))
    return etiquetas


def imagenes_de(directorio: Path) -> list[Path]:
    return sorted(p for p in directorio.rglob("*") if p.suffix.lower() in EXTENSIONES and "images" in p.parts)


def ruta_etiqueta(imagen: Path) -> Path:
    partes = list(imagen.parts)
    indice = len(partes) - 1 - partes[::-1].index("images")
    partes[indice] = "labels"
    return Path(*partes).with_suffix(".txt")


def cargar_fuente_roboflow(config: dict, directorio: Path, canonicas: list[str]) -> Fuente:
    """Lee una descarga de Roboflow y aplica el mapeo explícito de clases."""
    datos = yaml.safe_load((directorio / "data.yaml").read_text(encoding="utf-8"))
    nombres = datos["names"]
    nombres = [nombres[k] for k in sorted(nombres)] if isinstance(nombres, dict) else list(nombres)
    mapeo = {normalizar(origen): destino for origen, destino in config["mapeo"].items()}

    faltantes = [n for n in nombres if normalizar(n) not in mapeo]
    if faltantes:
        sys.exit(
            f"La fuente {config['slug']} trae clases sin mapear en fuentes.yaml: {faltantes}.\n"
            "Agrega cada una al mapeo (a una clase canónica o a `descartar`) y vuelve a correr."
        )
    invalidas = sorted({d for d in mapeo.values() if d != "descartar" and d not in canonicas})
    if invalidas:
        sys.exit(f"El mapeo de {config['slug']} apunta a clases que no son canónicas: {invalidas}")

    fuente = Fuente(config["slug"], config.get("licencia", "desconocida"))
    for imagen in imagenes_de(directorio):
        fuente.leidas += 1
        etiquetas: list[Etiqueta] = []
        for indice, cx, cy, ancho, alto in leer_etiquetas_yolo(ruta_etiqueta(imagen)):
            if not 0 <= indice < len(nombres):
                continue
            destino = mapeo[normalizar(nombres[indice])]
            if destino != "descartar":
                etiquetas.append((destino, cx, cy, ancho, alto))
        fuente.muestras.append(Muestra(fuente.nombre, imagen, etiquetas))
    return fuente


def cargar_fuente_local(carpeta: Path, canonicas: list[str]) -> Fuente:
    """Lee una carpeta de fotos propias anotadas (images/, labels/, classes.txt)."""
    ruta_clases = carpeta / "classes.txt"
    if not (carpeta / "images").is_dir() or not ruta_clases.exists():
        sys.exit(f"La carpeta local {carpeta} debe tener images/, labels/ y classes.txt")
    nombres = [n.strip() for n in ruta_clases.read_text(encoding="utf-8").splitlines() if n.strip()]
    desconocidas = [n for n in nombres if n not in canonicas]
    if desconocidas:
        sys.exit(f"{ruta_clases} usa clases que no son canónicas: {desconocidas}. Válidas: {canonicas}")
    fuente = Fuente(f"local:{carpeta.name}", "propia")
    for imagen in imagenes_de(carpeta):
        fuente.leidas += 1
        etiquetas = [
            (nombres[i], cx, cy, ancho, alto)
            for i, cx, cy, ancho, alto in leer_etiquetas_yolo(ruta_etiqueta(imagen))
            if 0 <= i < len(nombres)
        ]
        fuente.muestras.append(Muestra(fuente.nombre, imagen, etiquetas))
    return fuente


# --------------------------------------------------------- completar persona

def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """IoU de dos cajas (cx, cy, ancho, alto)."""
    ax1, ay1, ax2, ay2 = a[0] - a[2] / 2, a[1] - a[3] / 2, a[0] + a[2] / 2, a[1] + a[3] / 2
    bx1, by1, bx2, by2 = b[0] - b[2] / 2, b[1] - b[3] / 2, b[0] + b[2] / 2, b[1] + b[3] / 2
    ancho, alto = min(ax2, bx2) - max(ax1, bx1), min(ay2, by2) - max(ay1, by1)
    if ancho <= 0 or alto <= 0:
        return 0.0
    inter = ancho * alto
    return inter / (a[2] * a[3] + b[2] * b[3] - inter)


def completar_persona(fuente: Fuente, directorio: Path, config: dict) -> None:
    """Añade cajas de persona con el YOLO26 de COCO donde la fuente no las anotó.

    Las detecciones crudas se guardan en personas_coco.json dentro de la descarga, así
    que volver a correr el script no repite la inferencia.
    """
    cache = directorio / "personas_coco.json"
    detecciones: dict[str, list[list[float]]] = json.loads(cache.read_text()) if cache.exists() else {}
    pendientes = [m.ruta for m in fuente.muestras if m.ruta.name not in detecciones]
    if pendientes:
        from ultralytics import YOLO

        DIR_MODELOS.mkdir(parents=True, exist_ok=True)
        modelo = YOLO(str(DIR_MODELOS / config["modelo"]))  # Ultralytics lo descarga si falta
        print(f"  {fuente.nombre}: detectando personas en {len(pendientes)} imágenes…")
        for inicio in range(0, len(pendientes), 64):
            lote = pendientes[inicio:inicio + 64]
            resultados = modelo.predict(
                [str(p) for p in lote], classes=[0], conf=0.25, imgsz=config["imgsz"], verbose=False
            )
            for ruta, resultado in zip(lote, resultados):
                cajas = resultado.boxes
                detecciones[ruta.name] = [
                    [*(float(v) for v in xywhn), float(conf)]
                    for xywhn, conf in zip(cajas.xywhn.tolist(), cajas.conf.tolist())
                ]
        cache.write_text(json.dumps(detecciones))

    for muestra in fuente.muestras:
        if not muestra.etiquetas:
            continue  # sin EPP anotado la imagen no se usa: no vale la pena completarla
        anotadas = [e[1:] for e in muestra.etiquetas if e[0] == "persona"]
        for cx, cy, ancho, alto, confianza in detecciones.get(muestra.ruta.name, []):
            caja = (cx, cy, ancho, alto)
            if confianza < config["confianza"]:
                continue
            if any(_iou(caja, otra) >= config["iou_ya_anotada"] for otra in anotadas):
                continue
            muestra.etiquetas.append(("persona", *caja))
            anotadas.append(caja)
            fuente.personas_completadas += 1


# ------------------------------------------- duplicados y grupos de partición

class Conjuntos:
    """Unión-búsqueda mínima para agrupar índices."""

    def __init__(self, n: int) -> None:
        self.padre = list(range(n))

    def raiz(self, i: int) -> int:
        while self.padre[i] != i:
            self.padre[i] = self.padre[self.padre[i]]
            i = self.padre[i]
        return i

    def unir(self, a: int, b: int) -> None:
        ra, rb = self.raiz(a), self.raiz(b)
        if ra != rb:
            self.padre[max(ra, rb)] = min(ra, rb)


def calcular_phash(fuentes: list[Fuente], directorios: dict[str, Path]) -> None:
    """Hash perceptual de cada imagen, con caché por fuente (phash.json)."""
    import imagehash
    from PIL import Image

    for fuente in fuentes:
        cache = directorios[fuente.nombre] / "phash.json"
        conocidos: dict[str, str] = json.loads(cache.read_text()) if cache.exists() else {}
        nuevos = False
        for muestra in fuente.muestras:
            clave = muestra.ruta.name
            if clave not in conocidos:
                with Image.open(muestra.ruta) as imagen:
                    conocidos[clave] = str(imagehash.phash(imagen))
                nuevos = True
            muestra.phash = int(conocidos[clave], 16)
        if nuevos:
            cache.write_text(json.dumps(conocidos))


def agrupar(muestras: list[Muestra], distancia: int) -> tuple[Conjuntos, Conjuntos]:
    """Devuelve (duplicados, grupos de partición).

    Duplicados: imágenes con pHash a distancia de Hamming <= `distancia`.
    Grupos de partición: duplicados + copias aumentadas de Roboflow de una misma imagen
    original (comparten el nombre antes de ".rf."); todo el grupo va al mismo split para
    que validación y prueba no vean variantes de imágenes de entrenamiento.
    """
    import numpy as np

    n = len(muestras)
    duplicados, grupos = Conjuntos(n), Conjuntos(n)
    hashes = np.array([m.phash for m in muestras], dtype=np.uint64)
    for i in range(n - 1):
        cercanos = np.nonzero(np.bitwise_count(hashes[i + 1:] ^ hashes[i]) <= distancia)[0]
        for j in cercanos:
            duplicados.unir(i, i + 1 + int(j))
            grupos.unir(i, i + 1 + int(j))
    por_original: dict[tuple[str, str], int] = {}
    for i, muestra in enumerate(muestras):
        clave = (muestra.fuente, muestra.ruta.name.split(".rf.")[0])
        if clave in por_original:
            grupos.unir(por_original[clave], i)
        else:
            por_original[clave] = i
    return duplicados, grupos


def quitar_duplicados(muestras: list[Muestra], duplicados: Conjuntos, fuentes: dict[str, Fuente]) -> list[bool]:
    """De cada grupo de duplicados conserva la imagen con más etiquetas."""
    por_grupo: dict[int, list[int]] = defaultdict(list)
    for i in range(len(muestras)):
        por_grupo[duplicados.raiz(i)].append(i)
    conservar = [False] * len(muestras)
    for indices in por_grupo.values():
        mejor = max(indices, key=lambda i: (len(muestras[i].etiquetas), -i))
        conservar[mejor] = True
        for i in indices:
            if i != mejor:
                fuentes[muestras[i].fuente].duplicadas += 1
    return conservar


def partir(muestras: list[Muestra], grupos: Conjuntos, conservar: list[bool],
           fracciones: dict[str, float], semilla: int) -> None:
    """Asigna train/valid/test por grupos completos, con semilla fija."""
    por_grupo: dict[int, list[int]] = defaultdict(list)
    for i in range(len(muestras)):
        por_grupo[grupos.raiz(i)].append(i)
    claves = sorted(por_grupo)
    random.Random(semilla).shuffle(claves)
    total = sum(conservar)
    limite_train = fracciones["train"] * total
    limite_valid = limite_train + fracciones["valid"] * total
    acumulado = 0
    for clave in claves:
        split = "train" if acumulado < limite_train else "valid" if acumulado < limite_valid else "test"
        for i in por_grupo[clave]:
            muestras[i].split = split
            acumulado += conservar[i]


# ------------------------------------------------------------------- salida

def es_primer_plano(etiquetas: list[Etiqueta], config: dict) -> bool:
    """True si la imagen se parece al encuadre del stand (persona o elemento grandes)."""
    altos = [e[4] for e in etiquetas if e[0] == "persona"]
    anchos = [e[3] for e in etiquetas if e[0] in ("casco", "gafas")]
    return (bool(altos) and max(altos) >= config["alto_persona_min"]) or (
        bool(anchos) and max(anchos) >= config["ancho_elemento_min"]
    )


def enlazar_o_copiar(origen: Path, destino: Path) -> None:
    """Enlace duro si se puede (no gasta disco); si no, copia."""
    try:
        os.link(origen, destino)
    except OSError:
        shutil.copy2(origen, destino)


def escribir_dataset(muestras: list[Muestra], clases: list[str], salida: Path, config_pp: dict) -> int:
    """Escribe imágenes, etiquetas, data.yaml y la lista de primer plano. Devuelve cuántas hay."""
    if salida.exists():
        if DIR_DATASETS not in salida.resolve().parents:
            sys.exit(f"Por seguridad solo se limpia una salida dentro de {DIR_DATASETS}")
        shutil.rmtree(salida)
    indice = {clase: i for i, clase in enumerate(clases)}
    primer_plano: list[str] = []
    contador: Counter = Counter()
    for muestra in muestras:
        prefijo = re.sub(r"[^a-z0-9]+", "-", muestra.fuente.split("/")[-1].lower()).strip("-")
        contador[prefijo] += 1
        nombre = f"{prefijo}_{contador[prefijo]:06d}"
        dir_imagenes = salida / "images" / muestra.split
        dir_etiquetas = salida / "labels" / muestra.split
        dir_imagenes.mkdir(parents=True, exist_ok=True)
        dir_etiquetas.mkdir(parents=True, exist_ok=True)
        destino = dir_imagenes / (nombre + muestra.ruta.suffix.lower())
        enlazar_o_copiar(muestra.ruta, destino)
        lineas = [f"{indice[c]} {cx:.6f} {cy:.6f} {an:.6f} {al:.6f}" for c, cx, cy, an, al in muestra.etiquetas]
        (dir_etiquetas / (nombre + ".txt")).write_text("\n".join(lineas) + "\n", encoding="utf-8")
        if muestra.split in ("valid", "test") and es_primer_plano(muestra.etiquetas, config_pp):
            primer_plano.append(destino.as_posix())

    nombres = {i: clase for i, clase in enumerate(clases)}
    base = {"path": salida.as_posix(), "names": nombres}
    (salida / "data.yaml").write_text(
        yaml.safe_dump({**base, "train": "images/train", "val": "images/valid", "test": "images/test"},
                       sort_keys=False, allow_unicode=True), encoding="utf-8")
    (salida / "primer_plano.txt").write_text("\n".join(primer_plano) + "\n", encoding="utf-8")
    (salida / "data_primer_plano.yaml").write_text(
        yaml.safe_dump({**base, "train": "images/train", "val": "primer_plano.txt"},
                       sort_keys=False, allow_unicode=True), encoding="utf-8")
    return len(primer_plano)


def escribir_reporte(fuentes: list[Fuente], muestras: list[Muestra], clases: list[str],
                     quitadas: dict[str, int], primer_plano: int, minimo: int) -> str:
    """Reporte de balance de clases en Markdown."""
    instancias: dict[str, Counter] = {s: Counter() for s in ("train", "valid", "test")}
    imagenes: dict[str, Counter] = {s: Counter() for s in ("train", "valid", "test")}
    tamanos: dict[str, list[float]] = defaultdict(list)
    por_split: Counter = Counter()
    usadas: Counter = Counter()
    for muestra in muestras:
        por_split[muestra.split] += 1
        usadas[muestra.fuente] += 1
        for clase in {e[0] for e in muestra.etiquetas}:
            imagenes[muestra.split][clase] += 1
        for clase, _, _, ancho, alto in muestra.etiquetas:
            instancias[muestra.split][clase] += 1
            tamanos[clase].append(alto if clase == "persona" else ancho)

    lineas = [
        "# Balance del dataset de EPP industrial",
        "",
        "Generado por `python -m modulos.epp.datos.preparar_dataset`. No editar a mano.",
        "",
        f"Imágenes: {len(muestras)} (train {por_split['train']}, valid {por_split['valid']}, "
        f"test {por_split['test']}). Primer plano en valid+test: {primer_plano}.",
        "",
        "## Fuentes",
        "",
        "| Fuente | Licencia | Leídas | Sin etiquetas útiles | Duplicadas | Personas completadas | Usadas |",
        "|---|---|---|---|---|---|---|",
    ]
    for fuente in fuentes:
        lineas.append(
            f"| {fuente.nombre} | {fuente.licencia} | {fuente.leidas} | {fuente.sin_etiquetas} | "
            f"{fuente.duplicadas} | {fuente.personas_completadas} | {usadas[fuente.nombre]} |"
        )
    lineas += [
        "",
        "## Instancias por clase",
        "",
        "| Clase | train | valid | test | Imágenes en train | Tamaño mediano |",
        "|---|---|---|---|---|---|",
    ]
    for clase in clases:
        mediana = statistics.median(tamanos[clase]) if tamanos[clase] else 0.0
        medida = "alto" if clase == "persona" else "ancho"
        lineas.append(
            f"| {clase} | {instancias['train'][clase]} | {instancias['valid'][clase]} | "
            f"{instancias['test'][clase]} | {imagenes['train'][clase]} | {mediana:.2f} del {medida} |"
        )
    lineas += ["", "## Clases quitadas", ""]
    if quitadas:
        lineas += [f"- `{clase}`: {n} instancias en train (mínimo {minimo})." for clase, n in quitadas.items()]
    else:
        lineas.append("Ninguna.")
    lineas += [
        "",
        "## Lectura",
        "",
        "- «Tamaño mediano» es la fracción de la imagen que ocupa la caja: en el stand (1-2 m) la "
        "persona ocupa 0.6 o más del alto.",
        "- Los duplicados se detectan por pHash; las copias aumentadas de una misma imagen quedan "
        "en el mismo split.",
        "- Las fuentes con licencia CC BY 4.0 exigen atribución a sus autores.",
        "",
    ]
    texto = "\n".join(lineas)
    RUTA_REPORTE.write_text(texto, encoding="utf-8")
    return texto


# --------------------------------------------------------------------- main

def main() -> None:
    analizador = argparse.ArgumentParser(description="Prepara el dataset de EPP industrial")
    analizador.add_argument("--local", action="append", default=[], metavar="CARPETA",
                            help="Carpeta de fotos propias anotadas (se puede repetir)")
    analizador.add_argument("--salida", default=str(DIR_SALIDA))
    opciones = analizador.parse_args()

    load_dotenv(find_dotenv(usecwd=True))
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    config = yaml.safe_load(RUTA_FUENTES.read_text(encoding="utf-8"))
    canonicas: list[str] = config["clases_canonicas"]

    print("1/6 Descarga")
    fuentes: list[Fuente] = []
    directorios: dict[str, Path] = {}
    for definicion in config["fuentes"]:
        directorio = descargar(definicion["slug"], definicion["version"], config["formato_descarga"])
        fuente = cargar_fuente_roboflow(definicion, directorio, canonicas)
        directorios[fuente.nombre] = directorio
        fuentes.append(fuente)
    for carpeta in opciones.local:
        fuente = cargar_fuente_local(Path(carpeta).resolve(), canonicas)
        directorios[fuente.nombre] = Path(carpeta).resolve()
        fuentes.append(fuente)

    print("2/6 Completar la clase persona")
    completar = {d["slug"] for d in config["fuentes"] if d.get("completar_persona")}
    for fuente in fuentes:
        if fuente.nombre in completar:
            completar_persona(fuente, directorios[fuente.nombre], config["completar_persona"])

    for fuente in fuentes:
        con_etiquetas = [m for m in fuente.muestras if m.etiquetas]
        fuente.sin_etiquetas = len(fuente.muestras) - len(con_etiquetas)
        fuente.muestras = con_etiquetas

    print("3/6 Deduplicación")
    calcular_phash(fuentes, directorios)
    muestras = [m for fuente in fuentes for m in fuente.muestras]
    duplicados, grupos = agrupar(muestras, config["distancia_phash"])
    conservar = quitar_duplicados(muestras, duplicados, {f.nombre: f for f in fuentes})

    print("4/6 Partición")
    partir(muestras, grupos, conservar, config["fracciones"], config["semilla"])
    muestras = [m for m, ok in zip(muestras, conservar) if ok]

    print("5/6 Balance de clases")
    en_train = Counter(e[0] for m in muestras if m.split == "train" for e in m.etiquetas)
    minimo = config["minimo_instancias_train"]
    quitadas = {c: en_train[c] for c in config["clases_opcionales"] if en_train[c] < minimo}
    escasas = [c for c in OBLIGATORIAS if en_train[c] < minimo]
    if escasas:
        sys.exit(f"Clases obligatorias con menos de {minimo} instancias en train: "
                 f"{ {c: en_train[c] for c in escasas} }. Hacen falta más datos.")
    for clase, cantidad in quitadas.items():
        print(f"  AVISO: se quita la clase '{clase}' ({cantidad} instancias en train, mínimo {minimo})")
    clases = [c for c in canonicas if c not in quitadas]
    for muestra in muestras:
        muestra.etiquetas = [e for e in muestra.etiquetas if e[0] in clases]
    muestras = [m for m in muestras if m.etiquetas]

    print("6/6 Escritura")
    primer_plano = escribir_dataset(muestras, clases, Path(opciones.salida), config["primer_plano"])
    print()
    print(escribir_reporte(fuentes, muestras, clases, quitadas, primer_plano, minimo))
    print(f"Dataset en {opciones.salida}\nReporte en {RUTA_REPORTE}")


if __name__ == "__main__":
    main()
