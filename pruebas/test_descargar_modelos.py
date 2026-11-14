"""Descarga de modelos públicos, contra un servidor local: nada de estas pruebas sale a internet."""

import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from herramientas import descargar_modelos
from herramientas.descargar_modelos import MODELOS, ErrorDeDescarga, ModeloPublico, descargar, problema_de

CONTENIDO = b"pesos de mentira " * 5000
HUELLA = hashlib.sha256(CONTENIDO).hexdigest()


@pytest.fixture
def servidor():
    """Servidor HTTP local que entrega CONTENIDO en /modelo.pt y cuenta cuántas veces se lo piden."""
    pedidos = []

    class Manejador(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802  (nombre que exige http.server)
            pedidos.append(self.path)
            if self.path == "/redirige.pt":
                self.send_response(302)
                self.send_header("Location", "/modelo.pt")
                self.end_headers()
            elif self.path == "/modelo.pt":
                self.send_response(200)
                self.send_header("Content-Length", str(len(CONTENIDO)))
                self.end_headers()
                self.wfile.write(CONTENIDO)
            else:
                self.send_error(404)

        def log_message(self, *_):  # sin ruido en la salida de las pruebas
            pass

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    servidor.url = f"http://127.0.0.1:{servidor.server_address[1]}"
    servidor.pedidos = pedidos
    yield servidor
    servidor.shutdown()
    servidor.server_close()


def modelo_en(servidor, tmp_path, ruta="/modelo.pt", **cambios) -> ModeloPublico:
    datos = dict(nombre="modelo.pt", destino=tmp_path / "modelos" / "modelo.pt", url=servidor.url + ruta,
                 uso="Prueba", tamano=len(CONTENIDO), sha256=HUELLA)
    return ModeloPublico(**{**datos, **cambios})


def test_baja_el_modelo_que_falta_y_crea_su_carpeta(servidor, tmp_path):
    modelo = modelo_en(servidor, tmp_path)
    assert problema_de(modelo.destino, modelo) == "no está en disco"
    avisos = []
    assert descargar(modelo, informar=avisos.append) is True
    assert modelo.destino.read_bytes() == CONTENIDO
    assert problema_de(modelo.destino, modelo) is None
    assert HUELLA in avisos[-1]                                    # dice la huella de lo que bajó
    assert list(modelo.destino.parent.iterdir()) == [modelo.destino]   # sin archivos a medias


def test_si_ya_esta_y_es_el_esperado_no_lo_vuelve_a_bajar(servidor, tmp_path):
    modelo = modelo_en(servidor, tmp_path)
    descargar(modelo, informar=lambda _: None)
    assert descargar(modelo, informar=lambda _: None) is False
    assert len(servidor.pedidos) == 1
    assert descargar(modelo, forzar=True, informar=lambda _: None) is True   # salvo que se le pida
    assert len(servidor.pedidos) == 2


def test_sigue_las_redirecciones(servidor, tmp_path):
    modelo = modelo_en(servidor, tmp_path, ruta="/redirige.pt")
    assert descargar(modelo, informar=lambda _: None)
    assert modelo.destino.read_bytes() == CONTENIDO


def test_un_archivo_cortado_o_danado_en_disco_se_reemplaza(servidor, tmp_path):
    modelo = modelo_en(servidor, tmp_path)
    modelo.destino.parent.mkdir(parents=True)
    modelo.destino.write_bytes(CONTENIDO[:100])                    # una descarga anterior quedó a medias
    assert "pesa 100 bytes" in problema_de(modelo.destino, modelo)
    assert descargar(modelo, informar=lambda _: None) is True
    assert modelo.destino.read_bytes() == CONTENIDO

    modelo.destino.write_bytes(b"x" * len(CONTENIDO))              # mismo tamaño, otro contenido
    assert "huella" in problema_de(modelo.destino, modelo)
    assert descargar(modelo, informar=lambda _: None) is True
    assert modelo.destino.read_bytes() == CONTENIDO


@pytest.mark.parametrize("cambios, motivo", [
    (dict(sha256="0" * 64), "huella"),
    (dict(tamano=123), "pesa"),
], ids=["otra_huella", "otro_tamano"])
def test_si_lo_descargado_no_es_lo_esperado_no_se_deja_en_disco(servidor, tmp_path, cambios, motivo):
    modelo = modelo_en(servidor, tmp_path, **cambios)
    with pytest.raises(ErrorDeDescarga, match=motivo):
        descargar(modelo, informar=lambda _: None)
    assert list(modelo.destino.parent.iterdir()) == []


def test_si_el_servidor_no_lo_tiene_avisa_y_no_deja_nada(servidor, tmp_path):
    modelo = modelo_en(servidor, tmp_path, ruta="/no-existe.pt")
    with pytest.raises(ErrorDeDescarga, match="no se pudo bajar"):
        descargar(modelo, informar=lambda _: None)
    assert not modelo.destino.exists()


def test_el_comando_baja_lista_y_devuelve_error_si_algo_falla(servidor, tmp_path, capsys):
    bueno = modelo_en(servidor, tmp_path)
    malo = modelo_en(servidor, tmp_path, ruta="/no-existe.pt", nombre="otro.pt", destino=tmp_path / "modelos" / "otro.pt")

    assert descargar_modelos.main(["--listar"], modelos=(bueno, malo)) == 0
    assert capsys.readouterr().out.count("FALTA") == 2
    assert not bueno.destino.exists()                              # listar no descarga nada

    assert descargar_modelos.main([], modelos=(bueno, malo)) == 1  # uno bajó y el otro no
    salida = capsys.readouterr().out
    assert "listo en" in salida and "ERROR: otro.pt" in salida
    assert bueno.destino.is_file() and not malo.destino.exists()

    assert descargar_modelos.main([], modelos=(bueno,)) == 0
    assert "ya está" in capsys.readouterr().out


def test_el_catalogo_trae_el_modelo_de_pose_de_zona_con_su_huella():
    (pose,) = [modelo for modelo in MODELOS if modelo.nombre == "yolo26n-pose.pt"]
    assert pose.destino.parts[-4:] == ("modulos", "zona", "modelos", "yolo26n-pose.pt")
    assert pose.url.startswith("https://github.com/ultralytics/assets/releases/download/")
    assert pose.tamano and len(pose.sha256) == 64
