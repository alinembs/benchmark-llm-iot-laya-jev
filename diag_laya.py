#!/usr/bin/env python3
"""
diag_laya.py - diagnostico offline do Laya (sem MQTT, sem ESP32).

Pergunta: o que faz o ventilador nao responder, se a lampada responde bem?
Testa varias formas de escrever a MESMA pergunta com entradas fixas e mostra
a resposta completa do modelo (choice, confidence e qualquer outro campo).

Uso:  python3 diag_laya.py
Cole a saida inteira de volta no chat.
"""
import json

from laya import Router

MODEL = "multilingual"
DEVICE = "cuda"

agent = Router(preload=[MODEL], device=DEVICE)


def q(instr, crit):
    return {"type": "choice", "instructions": instr, "criteria": crit}


# cada variante: pergunta, texto "positivo" (deve ligar), texto "negativo",
# e os rotulos esperados para positivo/negativo
VARIANTES = {
    "A_faixa_atual": dict(
        q=q("O que fazer com o ventilador? Ligue se a sala está quente. Desligue se a sala está fria.",
            {"ligar": "a sala está quente", "desligar": "a sala está fria"}),
        pos="A sala está quente.", neg="A sala está fria.",
        esp=("ligar", "desligar")),
    "B_espelho_da_lampada": dict(
        q=q("O que fazer com o ventilador? Ligue se há calor. Desligue se não há calor.",
            {"ligar": "há calor na sala", "desligar": "não há calor na sala"}),
        pos="Há calor na sala.", neg="Não há calor na sala.",
        esp=("ligar", "desligar")),
    "C_ordem_invertida": dict(
        q=q("O que fazer com o ventilador? Ligue se a sala está quente. Desligue se a sala está fria.",
            {"desligar": "a sala está fria", "ligar": "a sala está quente"}),
        pos="A sala está quente.", neg="A sala está fria.",
        esp=("ligar", "desligar")),
    "D_rotulos_sim_nao": dict(
        q=q("O ventilador deve ficar ligado? Sim se a sala está quente. Não se a sala está fria.",
            {"sim": "a sala está quente", "nao": "a sala está fria"}),
        pos="A sala está quente.", neg="A sala está fria.",
        esp=("sim", "nao")),
    "F_CONTROLE_lampada": dict(
        q=q("O que fazer com a lâmpada? Ligue se há uma pessoa. Desligue se não há ninguém.",
            {"ligar": "há uma pessoa perto do sensor", "desligar": "não há ninguém perto do sensor"}),
        pos="Há uma pessoa perto do sensor.", neg="Não há ninguém perto do sensor.",
        esp=("ligar", "desligar")),
}


def chamar(estado, pergunta):
    return agent.predict({"sala": estado}, {"x": pergunta}, model=MODEL)["answers"]["x"]


def mostrar(nome, entrada, r):
    choice = r.get("choice")
    conf = r.get("confidence")
    conf_s = f"{conf:.2f}" if isinstance(conf, (int, float)) else str(conf)
    print(f"{nome:<22} {entrada:<40} -> {str(choice):<9} conf={conf_s} | raw={json.dumps(r, ensure_ascii=False, default=str)}")


print("\n=== Variantes de pergunta (entrada binaria) ===")
resumo = {}
for nome, v in VARIANTES.items():
    ok = 0
    for entrada, esperado in ((v["pos"], v["esp"][0]), (v["neg"], v["esp"][1])):
        r = chamar(entrada, v["q"])
        mostrar(nome, entrada, r)
        ok += int(r.get("choice") == esperado)
    resumo[nome] = ok
    print()

print("=== Variante numerica (pergunta original, varias temperaturas) ===")
Q_NUM = q(
    "O que fazer com o ventilador? Ligue se a temperatura for 30 graus Celsius ou mais. "
    "Desligue se a temperatura for menor que 30 graus Celsius.",
    {"ligar": "a temperatura é 30 graus Celsius ou mais",
     "desligar": "a temperatura é menor que 30 graus Celsius"})
ok_num = 0
temps = [20, 25, 28, 29.9, 30.0, 30.1, 32, 35, 40]
for t in temps:
    r = chamar(f"A temperatura é {t:.1f} graus Celsius.", Q_NUM)
    mostrar("E_numerica", f"{t:.1f} C", r)
    ok_num += int(r.get("choice") == ("ligar" if t >= 30 else "desligar"))

print("\n=== RESUMO (acertos) ===")
for nome, ok in resumo.items():
    print(f"{nome:<22} {ok}/2")
print(f"{'E_numerica':<22} {ok_num}/{len(temps)}")
