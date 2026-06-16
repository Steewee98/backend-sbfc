"""Genera le risposte WhatsApp con Claude (Anthropic API).

Env:
  ANTHROPIC_API_KEY   chiave API Anthropic
  WA_AI_MODEL         opzionale, default claude-sonnet-4-20250514
"""
import os
import anthropic

MODEL = os.environ.get('WA_AI_MODEL', 'claude-sonnet-4-20250514')

CALENDLY = 'https://calendly.com/sbfoodconsulting-info/30min'

SYSTEM = f"""Sei l'assistente WhatsApp di Simone Braghetta, founder di
SB Food Consulting: consulenza per ristoranti, bar, pizzerie e locali food
in Italia.

Stai rispondendo su WhatsApp a una persona che ci ha scritto dopo aver
visto una nostra inserzione (sponsorizzata). Il tuo obiettivo, in ordine:
1. Accoglierla e capire in breve che locale ha e di cosa ha bisogno.
2. Portarla a prenotare una chiamata conoscitiva gratuita di 30 minuti
   con Simone, condividendo il link: {CALENDLY}

Regole di stile:
- Italiano, tono caldo e professionale, dai del "tu".
- Messaggi BREVI da WhatsApp: 1-3 frasi, niente email formali, niente
  elenchi lunghi. Usa al massimo un'emoji ogni tanto, senza esagerare.
- Una domanda alla volta, conversazione naturale.

Regole di sicurezza (importanti):
- NON inventare prezzi, percentuali, garanzie di risultato, numeri o
  dettagli del servizio che non conosci. Se chiedono prezzi o dettagli
  specifici, spiega che li vede meglio Simone in chiamata.
- Non prendere impegni vincolanti a nome dell'azienda.
- Se il messaggio è chiaramente spam, offensivo o fuori contesto,
  rispondi in modo cortese e molto breve senza proseguire.
- Quando la persona è interessata o chiede come procedere, proponi
  subito il link {CALENDLY}.
"""


def _sanitizza(messaggi):
    """L'API richiede messaggi che iniziano con 'user' e alternano i ruoli.
    Unisce i consecutivi dello stesso ruolo e scarta gli 'assistant' iniziali."""
    puliti = []
    for m in messaggi:
        if not m.get('content'):
            continue
        if puliti and puliti[-1]['role'] == m['role']:
            puliti[-1]['content'] += '\n' + m['content']
        else:
            puliti.append({'role': m['role'], 'content': m['content']})
    while puliti and puliti[0]['role'] != 'user':
        puliti.pop(0)
    return puliti


def genera_risposta(messaggio_utente, nome='', storico=None):
    """Ritorna il testo della risposta, o None se l'AI non è disponibile."""
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        print("[WA-AI] ANTHROPIC_API_KEY mancante")
        return None

    messaggi = list(storico or [])
    messaggi.append({'role': 'user',
                     'content': messaggio_utente or '(nessun testo)'})
    messaggi = _sanitizza(messaggi)
    if not messaggi:
        return None

    system = SYSTEM
    if nome:
        system += f"\n\nIl nome del contatto è: {nome}."

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=MODEL,
            max_tokens=500,
            system=system,
            messages=messaggi,
        )
        return resp.content[0].text.strip()
    except Exception as e:
        print(f"[WA-AI] Errore generazione: {e}")
        return None
