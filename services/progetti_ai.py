"""Dalla nota dettata da Simone alle voci del progetto.

Entra la trascrizione della nota più lo stato attuale del progetto (a che punto è,
cose ancora da fare con il loro numero); esce, con uno strumento a schema fisso:
cose fatte, cose nuove da fare (urgenti o no), quali cose da fare risultano chiuse,
il nuovo «a che punto siamo» ed eventualmente il nuovo stato.

Il modello non scrive nel database: restituisce una proposta che routes/progetti.py
ricontrolla (numeri che esistono davvero, testi non vuoti, date valide) prima di salvarla.
"""
import logging
import os

logger = logging.getLogger(__name__)

MODELLO = os.environ.get('PROGETTI_MODELLO', 'claude-sonnet-5')
STATI = ['aperto', 'in_lavorazione', 'in_attesa', 'chiuso']

SISTEMA = """Aiuti Simone Braghetta, consulente di ristorazione, a tenere il punto dei suoi progetti. Simone detta al telefono una nota su un progetto; la trascrizione automatica può avere errori, parole spezzate e ripetizioni. Leggila e aggiorna il progetto con lo strumento `aggiorna`.

Regole:
- `fatti`: cose che Simone dice di aver fatto o che sono successe (riunioni fatte, materiali mandati, decisioni prese). Frasi brevi al participio passato, senza «ho»: «Mandato il preventivo a Marco», «Chiusi gli inviti», «Deciso il menù di apertura». Mai all'infinito: l'infinito è per le cose da fare.
- `da_fare`: cose nuove da fare che la nota nomina. Una voce per cosa, frase breve che comincia con un verbo: «Chiamare il fornitore del forno». `urgente` true solo se Simone dice che è urgente, che va fatta subito/oggi/domani/entro pochi giorni, o se c'è una scadenza entro 7 giorni da oggi. `scadenza` solo se la nota dà un giorno preciso o ricavabile («venerdì», «il 20»), in formato AAAA-MM-GG; altrimenti null.
- Non ripetere in `da_fare` una cosa già presente tra quelle aperte: se la nota la rende urgente, mettila in `urgenti` con il suo numero.
- `completate`: i numeri delle cose da fare aperte che la nota dice fatte. Solo numeri della lista che ti viene data, solo se la nota lo dice chiaramente. Una cosa completata va anche in `fatti`, scritta come fatto.
- `punto`: una o due frasi su a che punto è il progetto adesso, tenendo conto di quello di prima e della nota. Concreto, niente frasi di circostanza. Le date scritte a parole («martedì 20 ottobre»), mai nel formato AAAA-MM-GG.
- `stato`: cambialo solo se la nota lo dice (progetto partito, fermo in attesa di qualcuno, chiuso/consegnato); altrimenti null.
- Non inventare nulla che la nota non dica. Nomi di persone e locali come li dice Simone; correggi solo errori evidenti di trascrizione.
- Se la nota non contiene niente di utile, restituisci liste vuote e `punto` come stringa vuota: resta quello di prima."""

STRUMENTO = {
    'name': 'aggiorna',
    'description': 'Aggiorna il progetto con quello che dice la nota.',
    'input_schema': {
        'type': 'object',
        'properties': {
            'fatti': {'type': 'array', 'items': {'type': 'string'}},
            'da_fare': {'type': 'array', 'items': {
                'type': 'object',
                'properties': {
                    'testo': {'type': 'string'},
                    'urgente': {'type': 'boolean'},
                    'scadenza': {'type': ['string', 'null'], 'description': 'AAAA-MM-GG'},
                },
                'required': ['testo', 'urgente', 'scadenza'],
            }},
            'completate': {'type': 'array', 'items': {'type': 'integer'}},
            'urgenti': {'type': 'array', 'items': {'type': 'integer'},
                        'description': 'numeri di cose da fare già aperte che la nota rende urgenti'},
            'punto': {'type': 'string'},
            'stato': {'type': ['string', 'null'], 'enum': STATI + [None]},
        },
        'required': ['fatti', 'da_fare', 'completate', 'urgenti', 'punto', 'stato'],
    },
}


class NotaNonElaborata(Exception):
    pass


def chiama(testo_utente):
    """Una chiamata al modello; in un punto solo, così i test la sostituiscono."""
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'), timeout=60, max_retries=2)
    r = client.messages.create(
        model=MODELLO, max_tokens=2000, system=SISTEMA, tools=[STRUMENTO],
        tool_choice={'type': 'tool', 'name': 'aggiorna'},
        messages=[{'role': 'user', 'content': testo_utente}])
    for b in r.content:
        if b.type == 'tool_use':
            logger.info('Nota progetto: %s token in, %s out', r.usage.input_tokens, r.usage.output_tokens)
            return b.input
    raise NotaNonElaborata('Risposta senza aggiornamento')


def componi(nome, stato, punto, aperte, nota, oggi):
    """Il messaggio per il modello. `aperte` = [(id, testo, urgente, scadenza)]."""
    righe = [f'Oggi è {oggi.isoformat()} ({_GIORNI[oggi.weekday()]}).',
             f'Progetto: {nome}', f'Stato: {stato}', f'A che punto era: {punto or "nessun aggiornamento finora"}', '',
             'Cose da fare ancora aperte:']
    if aperte:
        for i, t, u, s in aperte:
            extra = ' [urgente]' if u else ''
            extra += f' [entro {s.isoformat()}]' if s else ''
            righe.append(f'{i}. {t}{extra}')
    else:
        righe.append('(nessuna)')
    righe += ['', 'Nota di Simone (trascrizione):', nota.strip()]
    return '\n'.join(righe)


_GIORNI = ['lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato', 'domenica']


def elabora(nome, stato, punto, aperte, nota, oggi):
    if not os.environ.get('ANTHROPIC_API_KEY'):
        raise NotaNonElaborata('Lettura delle note non attiva su questo server')
    try:
        return chiama(componi(nome, stato, punto, aperte, nota, oggi))
    except NotaNonElaborata:
        raise
    except Exception as e:
        logger.error('Nota progetto non elaborata: %s', e)
        raise NotaNonElaborata('Elaborazione non riuscita adesso')
