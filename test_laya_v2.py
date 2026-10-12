#!/usr/bin/env python3
"""
test_laya_v2.py - Laya adaptado para as mesmas 4 situacoes do Jev.

Mudancas em relacao ao v1:
  1. Cada pergunta recebe SO a informacao que importa a ela
     (ventilador ve so temperatura; lampada ve so presenca).
     No v1 o ventilador seguia a presenca por causa do texto misturado.
  2. Uma chamada por pergunta (estado isolado).
  3. Duas variantes de entrada para a temperatura (VARIANTE):
       numero -> "A temperatura e 35.1 graus Celsius." (o modelo compara o numero)
       faixa  -> "A sala esta quente." / "A sala esta fria."
                 ATENCAO: aqui o script ja converte numero em quente/frio,
                 entao parte da decisao sai do modelo. Use so para diagnostico
                 e registre isso ao comparar com o Jev.
  4. Placar de acertos por transicao (so conta quando o estado muda).

Uso:
  python3 test_laya_v2.py            # variante numero (justa p/ comparar com Jev)
  VARIANTE=faixa python3 test_laya_v2.py

Desligue a automacao fixa do ESP32 antes. Nao rode junto com o Jev.
"""
import json
import os
import time

import paho.mqtt.client as mqtt

MODEL = "multilingual"
DEVICE = "cuda"
BROKER = "localhost"
PORTA = 1883
BASE = "casa/sala1"
TEMP_REF = 30.0          # log "esperado"; so entra na entrada na variante 'faixa'
INTERVALO_S = 2.0
STALE_S = 10.0
VARIANTE = os.environ.get("VARIANTE", "numero").strip().lower()

T_DADOS = f"{BASE}/dados"
T_STATUS = f"{BASE}/status"
T_SET = {"rele": f"{BASE}/rele/set", "led": f"{BASE}/led/set"}
NOMES = {"rele": "ventilador", "led": "lâmpada"}
T_AUTO = "casa/jetson/auto"
T_DECISAO = "casa/jetson/decisao"
T_JETSON_STATUS = "casa/jetson/status"

# --- Perguntas: cada uma fala so do seu assunto ---------------------------
if VARIANTE == "faixa":
    Q_VENT = {
        "type": "choice",
        "instructions": "O que fazer com o ventilador? Ligue se a sala está quente. Desligue se a sala está fria.",
        "criteria": {
            "ligar": "a sala está quente",
            "desligar": "a sala está fria",
        },
    }
else:
    Q_VENT = {
        "type": "choice",
        "instructions": (
            "O que fazer com o ventilador? "
            "Ligue se a temperatura for 30 graus Celsius ou mais. "
            "Desligue se a temperatura for menor que 30 graus Celsius."
        ),
        "criteria": {
            "ligar": "a temperatura é 30 graus Celsius ou mais",
            "desligar": "a temperatura é menor que 30 graus Celsius",
        },
    }

Q_LAMP = {
    "type": "choice",
    "instructions": "O que fazer com a lâmpada? Ligue se há uma pessoa. Desligue se não há ninguém.",
    "criteria": {
        "ligar": "há uma pessoa perto do sensor",
        "desligar": "não há ninguém perto do sensor",
    },
}

est = {
    "t": None, "cm": None, "base": None, "p": None, "sensor_ok": 0,
    "rele": "OFF", "led": "OFF",
    "online": False, "visto": 0.0, "auto": True,
}
ultimo = 0.0
agent = None
placar = {"rele": [0, 0], "led": [0, 0]}      # [acertos, total] por amostra
trans = {"rele": [0, 0], "led": [0, 0]}       # por mudanca de situacao
prev_esp = {"rele": None, "led": None}


def carregar_modelo():
    global agent
    from laya import Router

    agent = Router(preload=[MODEL], device=DEVICE)
    agent.predict({"x": "aquecimento"}, {"x": Q_LAMP}, model=MODEL)
    print("Laya pronto:", MODEL, "em", DEVICE, "| variante:", VARIANTE)


def texto_temperatura():
    t = est["t"]
    if VARIANTE == "faixa":
        return "A sala está quente." if t >= TEMP_REF else "A sala está fria."
    return f"A temperatura é {t:.1f} graus Celsius."


def texto_presenca():
    if est["p"]:
        return "Há uma pessoa perto do sensor."
    return "Não há ninguém perto do sensor."


def perguntar(estado_chave, texto, nome, pergunta):
    r = agent.predict({estado_chave: texto}, {nome: pergunta}, model=MODEL)["answers"]
    return r[nome]["choice"], float(r[nome]["confidence"])


def comandar(c, saida, novo):
    if est[saida] == novo or not est["auto"]:
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


def contar(saida, ok, esperado_val):
    placar[saida][1] += 1
    placar[saida][0] += int(ok)
    if prev_esp[saida] != esperado_val:      # mudou a situacao esperada
        trans[saida][1] += 1
        trans[saida][0] += int(ok)
        prev_esp[saida] = esperado_val


def decidir(c):
    global ultimo
    if not est["auto"] or not dados_validos():
        return
    if time.time() - ultimo < INTERVALO_S:
        return
    ultimo = time.time()

    t0 = time.perf_counter()
    try:
        vent, conf_v = perguntar("temperatura", texto_temperatura(), "ventilador", Q_VENT)
        lamp, conf_l = perguntar("presenca", texto_presenca(), "lampada", Q_LAMP)
    except Exception as e:
        print("Erro no Laya:", e)
        return
    ms = (time.perf_counter() - t0) * 1000

    comandar(c, "rele", "ON" if vent == "ligar" else "OFF")
    comandar(c, "led", "ON" if lamp == "ligar" else "OFF")

    esp_rele, esp_led = esperado()
    ok_r = est["rele"] == esp_rele
    ok_l = est["led"] == esp_led
    contar("rele", ok_r, esp_rele)
    contar("led", ok_l, esp_led)

    log = {
        "modelo": "laya-v2", "variante": VARIANTE,
        "t": est["t"], "p_esp": est["p"], "cm": est["cm"],
        "ventilador": vent, "conf_ventilador": round(conf_v, 2),
        "lampada": lamp, "conf_lampada": round(conf_l, 2),
        "rele": est["rele"], "led": est["led"],
        "esperado_rele": esp_rele, "esperado_led": esp_led,
        "ok_rele": ok_r, "ok_led": ok_l,
        "ms": round(ms),
    }
    c.publish(T_DECISAO, json.dumps(log))
    print(log)


def resumo():
    print("\n=== PLACAR (variante: %s) ===" % VARIANTE)
    for k in ("rele", "led"):
        a, n = placar[k]
        ta, tn = trans[k]
        pct = (100 * a / n) if n else 0
        print(f"{NOMES[k]:<11} amostras: {a}/{n} ({pct:.0f}%) | "
              f"1a leitura apos cada mudanca: {ta}/{tn}")


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
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="jetson-laya2")
    except AttributeError:
        c = mqtt.Client(client_id="jetson-laya2")
    c.will_set(T_JETSON_STATUS, "offline", qos=1, retain=True)
    c.on_connect = on_connect
    c.on_message = on_msg
    return c


def main():
    carregar_modelo()
    c = criar_cliente()
    c.connect(BROKER, PORTA, keepalive=30)
    try:
        c.loop_forever()
    except KeyboardInterrupt:
        print("\nEncerrando Laya v2...")
    finally:
        resumo()
        c.publish(T_JETSON_STATUS, "offline", qos=1, retain=True)
        c.disconnect()


if __name__ == "__main__":
    main()
