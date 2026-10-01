"""Chi lavora in un locale della ristorazione: le mansioni, i reparti e i contratti.

La mansione dice cosa fa la persona (pizzaiolo, cameriere, lavapiatti…) e porta con sé
il reparto, che serve a dividere il costo del personale (quanto costa la cucina, quanto la
sala). Il ruolo in PersonaLocale resta l'accesso: chi legge il quadro e chi timbra soltanto.
"""

REPARTI = {
    'cucina': 'Cucina', 'pizzeria': 'Pizzeria', 'pasticceria': 'Pasticceria', 'sala': 'Sala', 'bar': 'Bar',
    'cassa': 'Cassa e accoglienza', 'lavaggio': 'Lavaggio e pulizie', 'consegne': 'Consegne', 'direzione': 'Direzione',
}

# mansione → reparto, nell'ordine in cui compaiono nel menù a tendina
MANSIONI = {
    'Chef': 'cucina', 'Sous chef': 'cucina', 'Capo partita': 'cucina', 'Cuoco': 'cucina', 'Aiuto cuoco': 'cucina',
    'Commis di cucina': 'cucina', 'Preparatore': 'cucina',
    'Pizzaiolo': 'pizzeria', 'Aiuto pizzaiolo': 'pizzeria', 'Fornaio': 'pizzeria',
    'Pasticcere': 'pasticceria', 'Aiuto pasticcere': 'pasticceria',
    'Maître': 'sala', 'Responsabile di sala': 'sala', 'Cameriere': 'sala', 'Commis di sala': 'sala', 'Runner': 'sala',
    'Sommelier': 'sala',
    'Capo barman': 'bar', 'Barman': 'bar', 'Barista': 'bar',
    'Cassiere': 'cassa', 'Accoglienza': 'cassa',
    'Lavapiatti': 'lavaggio', 'Addetto pulizie': 'lavaggio',
    'Rider': 'consegne',
    'Direttore': 'direzione', 'Amministrazione': 'direzione', 'Titolare': 'direzione',
}

CONTRATTI = ['Indeterminato full-time', 'Indeterminato part-time', 'Determinato', 'Apprendistato', 'Stagionale',
             'A chiamata / extra', 'Tirocinio', 'Socio o familiare', 'Collaboratore esterno']


def reparto_di(mansione):
    return MANSIONI.get(mansione)
