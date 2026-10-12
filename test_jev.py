#!/usr/bin/env python3
"""
iot_jev.py - teste do Jev nas mesmas 4 situacoes do Laya.
O modelo decide. A regra de 30 C so entra no log, para comparar.
  export OPENCODE_API_KEY=...
Desligue a automacao fixa do ESP32 antes de rodar.
Nao rode junto com o iot_laya.py.
"""
import json
import os
import time
import urllib.error
import urllib.request

import paho.mqtt.client as mqtt

API_URL = "https://opencode.ai/zen/v1/systemone"
MODEL = "jev-1.13-free"
TIMEOUT_S = 8.0
BROKER = "localhost"
PORTA = 1883
BASE = "casa/sala1"
TEMP_REF = 30.0
INTERVALO_S = 2.0
STALE_S = 10.0
MARGEM_DIST = 20.0
API_KEY = os.environ.get("OPENCODE_API_KEY", "").strip()

T_DADOS = f"{BASE}/dados"
T_STATUS = f"{BASE}/status"
T_SET = {"rele": f"{BASE}/rele/set", "led": f"{BASE}/led/set"}
NOMES = {"rele": "ventilador", "led": "lâmpada"}
T_AUTO = "casa/jetson/auto"
T_DECISAO = "casa/jetson/decisao"
T_JETSON_STATUS = "casa/jetson/status"

QUESTIONS = {
    "ventilador": {
        "type": "choice",
        "instructions": (
            "O que fazer com o ventilador? "
            "Ligue se a temperatura for 30 graus Celsius ou mais, com ou sem pessoa. "
            "Desligue se a temperatura for menor que 30 graus Celsius, com ou sem pessoa."
        ),
        "criteria": {
            "ligar": "a temperatura é de 30 graus Celsius ou mais",
            "desligar": "a temperatura é menor que 30 graus Celsius",
        },
    },
    "lampada": {
        "type": "choice",
        "instructions": (
            "O que fazer com a lâmpada? "
            "Ligue se houver uma pessoa. Desligue se não houver pessoa. "
            "A temperatura não importa."
        ),
        "criteria": {
            "ligar": "há uma pessoa perto do sensor",
            "desligar": "não há ninguém perto do sensor",
        },
    },
}

est = {
    "t": None, "cm": None, "base": None, "p": None, "sensor_ok": 0,
    "rele": "OFF", "led": "OFF",
    "online": False, "visto": 0.0, "auto": True,
}
ultimo = 0.0


def descrever():
    partes = [f"A temperatura da sala é {est['t']:.1f} graus Celsius."]
    if est["p"]:
        partes.append("Há uma pessoa perto do sensor.")
        cm, base = est["cm"], est["base"]
        if cm is not None and base is not None and cm < base - MARGEM_DIST:
            partes.append(f"A pessoa está a {cm:.0f} centímetros do sensor.")
    else:
        partes.append("Não há ninguém perto do sensor.")
    return " ".join(partes)


def perguntar(state):
    body = json.dumps({
        "model": MODEL,
        "state": {"sala": state},
        "questions": QUESTIONS,
    }).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "iot-jev-jetson/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))["answers"]


def comandar(c, saida, novo):
    if est[saida] == novo:
        return
    if not est["auto"]:
        return
    c.publish(T_SET[saida], novo, qos=1, retain=False)
    est[saida] = novo
    print(f"-> {NOMES[saida]}: {novo}")


def esperado():
    pessoa = est["p"] == 1
    quente = est["t"] is not None and est["t"] >= TEMP_REF
    return ("ON" if quente else "OFF"), ("ON" if pessoa else "OFF")


def dados_validos():
    return (est["online"]
            and time.time() - est["visto"] <= STALE_S
            and est["t"] is not None
            and est["p"] is not None
            and est["sensor_ok"] == 1)


def decidir(c):
    global ultimo
    if not est["auto"] or not dados_validos():
        return
    if time.time() - ultimo < INTERVALO_S:
        return
    ultimo = time.time()

    t0 = time.perf_counter()
    try:
        r = perguntar(descrever())
    except urllib.error.HTTPError as e:
        print("Erro Jev HTTP", e.code, e.read().decode(errors="ignore")[:300])
        return
    except Exception as e:
        print("Erro Jev:", e)
        return
    ms = (time.perf_counter() - t0) * 1000

    acao = r["ventilador"]["choice"]
    lamp = r["lampada"]["choice"]
    if acao == "ligar":
        comandar(c, "rele", "ON")
    elif acao == "desligar":
        comandar(c, "rele", "OFF")
    if lamp == "ligar":
        comandar(c, "led", "ON")
    elif lamp == "desligar":
        comandar(c, "led", "OFF")

    esp_rele, esp_led = esperado()
    log = {
        "modelo": MODEL,
        "t": est["t"], "p_esp": est["p"], "cm": est["cm"],
        "ventilador": acao, "conf_ventilador": round(r["ventilador"]["confidence"], 2),
        "lampada": lamp, "conf_lampada": round(r["lampada"]["confidence"], 2),
        "rele": est["rele"], "led": est["led"],
        "esperado_rele": esp_rele, "esperado_led": esp_led,
        "ok_rele": est["rele"] == esp_rele, "ok_led": est["led"] == esp_led,
        "ms": round(ms),
    }
    c.publish(T_DECISAO, json.dumps(log))
    print(log)


def on_msg(c, u, m):
    payload = m.payload.decode(errors="ignore").strip()
    if m.topic == T_STATUS:
        est["online"] = (payload == "online")
        print("ESP32:", payload)
        return
    if m.topic == T_AUTO:
        est["auto"] = payload.lower() in ("on", "1", "true")
        print("Automacao:", "LIGADA" if est["auto"] else "DESLIGADA (so observa)")
        return
    if m.topic != T_DADOS:
        return
    try:
        d = json.loads(payload)
    except ValueError:
        print("JSON invalido em", m.topic)
        return
    est["t"] = d.get("t") if d.get("tok") else None
    est["cm"] = d.get("d")
    est["base"] = d.get("base")
    est["p"] = d.get("p")
    est["sensor_ok"] = d.get("ok", 0)
    est["rele"] = "ON" if d.get("rele") else "OFF"
    est["led"] = "ON" if d.get("led") else "OFF"
    est["visto"] = time.time()
    est["online"] = True
    decidir(c)


def on_connect(c, u, flags, rc, *extra):
    falhou = rc.is_failure if hasattr(rc, "is_failure") else rc != 0
    if falhou:
        print("MQTT: falha ao conectar:", rc)
        return
    print("MQTT: conectado")
    c.subscribe([(T_DADOS, 0), (T_STATUS, 0), (T_AUTO, 0)])
    c.publish(T_JETSON_STATUS, "online", retain=True)


def criar_cliente():
    try:
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="jetson-jev")
    except AttributeError:
        c = mqtt.Client(client_id="jetson-jev")
    c.will_set(T_JETSON_STATUS, "offline", qos=1, retain=True)
    c.on_connect = on_connect
    c.on_message = on_msg
    return c


def main():
    if not API_KEY:
        raise SystemExit("defina OPENCODE_API_KEY")
    c = criar_cliente()
    c.connect(BROKER, PORTA, keepalive=30)
    try:
        c.loop_forever()
    except KeyboardInterrupt:
        print("\nEncerrando Jev...")
    finally:
        c.publish(T_JETSON_STATUS, "offline", qos=1, retain=True)
        c.disconnect()


if __name__ == "__main__":
    main()