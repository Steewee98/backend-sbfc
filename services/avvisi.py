"""Gli avvisi della Rete SB (fase 2, passo 11): una email al mattino, solo se c'è qualcosa.

Per ogni locale si guarda:
  - il semaforo del food cost: si avvisa quando peggiora, non ogni giorno;
  - la chiusura di ieri sera: se c'era servizio e nessuno l'ha segnata;
  - i turni dimenticati: aperti da più di 14 ore.

Va a Simone (RETE_AVVISI_EMAIL, più indirizzi separati da virgola) e ai titolari
del locale che hanno un'email. Si manda una volta al giorno, alle 9 di Roma.
"""
import html
import logging
import os
from datetime import datetime, timedelta

from models import db, LocaleRete, InventarioRete, VenditaRete, PersonaLocale, TurnoRete, ChiusuraRete
from services.quadro import giorno_di_lavoro, ora_locale

logger = logging.getLogger(__name__)
PESO = {'vuoto': 0, 'buono': 0, 'attesa': 1, 'fuori': 2}


def messaggi(locale, oggi=None):
    """→ (messaggi, nuovo semaforo). Non scrive niente."""
    from services.foodcost import diagnosi
    from routes.rete_foodcost import semaforo
    oggi = oggi or giorno_di_lavoro()
    out = []
    prima = ((locale.impostazioni or {}).get('avvisi') or {}).get('semaforo', 'vuoto')
    chiusi = (InventarioRete.query.filter_by(locale_id=locale.id, chiuso=True)
              .order_by(InventarioRete.giorno.desc()).limit(2).all())
    d = diagnosi(locale, chiusi[1], chiusi[0]) if len(chiusi) == 2 else None
    s = semaforo(d)
    if PESO[s] > PESO.get(prima, 0):
        out.append(f"Food cost {'fuori parametro' if s == 'fuori' else 'da tenere d’occhio'}: {d['frase']} "
                   f"(vero {str(d['food_cost_reale']).replace('.', ',')}%, obiettivo {str(d['obiettivo']).replace('.', ',')}%)")

    ieri = oggi - timedelta(days=1)
    ha_servito = (VenditaRete.query.filter_by(locale_id=locale.id, giorno=ieri).first()
                  or TurnoRete.query.filter(TurnoRete.locale_id == locale.id,
                                            TurnoRete.inizio >= datetime.utcnow() - timedelta(hours=40)).first())
    ha_persone = PersonaLocale.query.filter_by(locale_id=locale.id, attiva=True).first()
    if ha_servito and ha_persone and not ChiusuraRete.query.filter_by(locale_id=locale.id, giorno=ieri).first():
        out.append('Ieri sera la chiusura non è stata segnata.')

    for t in TurnoRete.query.filter(TurnoRete.locale_id == locale.id, TurnoRete.fine.is_(None),
                                    TurnoRete.inizio < datetime.utcnow() - timedelta(hours=14)).all():
        p = db.session.get(PersonaLocale, t.persona_id)
        out.append(f"Turno di {p.nome if p else '?'} aperto dal {ora_locale(t.inizio).strftime('%d/%m alle %H:%M')}: "
                   'manca la fine, va sistemato dalla console.')
    return out, s


def destinatari(locale):
    simone = [x.strip() for x in (os.environ.get('RETE_AVVISI_EMAIL') or '').split(',') if x.strip()]
    titolari = [p.email for p in PersonaLocale.query.filter_by(locale_id=locale.id, attiva=True).all()
                if p.email and p.ruolo in ('titolare', 'responsabile')]
    return list(dict.fromkeys(simone + titolari))


def _invia(a, oggetto, righe):
    import resend
    resend.api_key = os.environ.get('RESEND_API_KEY')
    corpo = ''.join(f'<li style="margin:0 0 10px">{html.escape(r)}</li>' for r in righe)
    resend.Emails.send({
        'from': os.environ.get('MAIL_FROM', 'SB Food Consulting <onboarding@resend.dev>'),
        'to': a, 'subject': oggetto,
        'html': f'<div style="font-family:Arial,sans-serif;font-size:15px;color:#1a1a1a;line-height:1.5">'
                f'<p>Buongiorno,</p><ul style="padding-left:18px">{corpo}</ul>'
                f'<p style="color:#6b6560;font-size:13px">Rete SB · SB Food Consulting</p></div>',
        'text': 'Buongiorno,\n\n' + '\n'.join('- ' + r for r in righe) + '\n\nRete SB · SB Food Consulting',
        'tags': [{'name': 'categoria', 'value': 'rete-avvisi'}],
    })


def giro(invia=True, oggi=None):
    """Tutti i locali: prepara (e se `invia`, manda) gli avvisi. → [{locale, a, messaggi}]"""
    oggi = oggi or giorno_di_lavoro()
    esito = []
    for l in LocaleRete.query.all():
        imp = dict(l.impostazioni or {})
        stato = dict(imp.get('avvisi') or {})
        if invia and stato.get('giorno') == oggi.isoformat():
            continue                                    # già fatto oggi
        righe, s = messaggi(l, oggi)
        a = destinatari(l)
        esito.append({'locale': l.nome, 'a': a, 'messaggi': righe})
        if not invia:
            continue
        if righe and a:
            try:
                _invia(a, f'{l.nome}: {len(righe)} {"cosa" if len(righe) == 1 else "cose"} da guardare', righe)
            except Exception as e:                      # un errore di posta non ferma gli altri locali
                logger.error('Avvisi rete, invio per %s fallito: %s', l.nome, e)
                continue
        stato.update({'semaforo': s, 'giorno': oggi.isoformat()})
        imp['avvisi'] = stato
        l.impostazioni = imp
    if invia:
        db.session.commit()
    return esito
