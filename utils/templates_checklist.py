def _area_peggiore(data):
    aree = {
        'Food Cost': data.get('punteggio_food_cost', 0),
        'Personale': data.get('punteggio_personale', 0),
        'Menu': data.get('punteggio_menu', 0),
        'Comunicazione': data.get('punteggio_comunicazione', 0),
        'Numeri': data.get('punteggio_numeri', 0)
    }
    nome = min(aree, key=aree.get)
    return nome, aree[nome]


def _punteggi_html(data):
    aree = [
        ('Food Cost', data.get('punteggio_food_cost', 0)),
        ('Personale', data.get('punteggio_personale', 0)),
        ('Menu', data.get('punteggio_menu', 0)),
        ('Comunicazione', data.get('punteggio_comunicazione', 0)),
        ('Numeri', data.get('punteggio_numeri', 0)),
    ]
    rows = ''
    for nome_area, val in aree:
        colore = '#c4622d' if val <= 1 else ('#e8a838' if val <= 2 else '#5a5a5a')
        rows += f"""<tr>
            <td style="padding:10px 0;border-bottom:1px solid #edeae5;
            font-size:14px;color:#1a1a1a">{nome_area}</td>
            <td style="padding:10px 0;border-bottom:1px solid #edeae5;
            font-size:14px;font-weight:bold;color:{colore};
            text-align:right">{val}/3</td>
            </tr>"""
    return rows


def _header(titolo_html):
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#f5f2ee;
font-family:Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="padding:40px 20px">
<table width="600" cellpadding="0" cellspacing="0"
style="max-width:600px;width:100%">

<!-- HEADER -->
<tr><td style="background:#37393f;padding:40px;
text-align:center;border-radius:6px 6px 0 0">
    <p style="color:#c4622d;font-size:11px;
    letter-spacing:3px;margin:0 0 12px;
    text-transform:uppercase;font-weight:bold">
    SB Food Consulting</p>
    <h1 style="color:#fff;font-family:Georgia,serif;
    font-size:22px;margin:0;font-weight:400;
    line-height:1.4">{titolo_html}</h1>
</td></tr>"""


def _punteggio_badge(punteggio):
    return f"""
<!-- PUNTEGGIO -->
<tr><td style="background:#c4622d;padding:24px 40px;
text-align:center">
    <p style="color:rgba(255,255,255,0.8);
    font-size:12px;margin:0 0 8px;
    text-transform:uppercase;letter-spacing:2px">
    Il tuo punteggio</p>
    <p style="color:#fff;font-size:48px;
    font-weight:bold;margin:0;
    font-family:Georgia,serif">
    {punteggio}<span style="font-size:24px">/15</span></p>
</td></tr>"""


def _footer():
    return """
<!-- FOOTER -->
<tr><td style="background:#37393f;padding:24px 40px;
text-align:center;border-radius:0 0 6px 6px">
    <p style="color:rgba(255,255,255,0.5);font-size:12px;
    margin:0 0 8px">SB Food Consulting &mdash; Roma, Italia</p>
    <p style="color:rgba(255,255,255,0.4);font-size:11px;
    margin:0">info@sbfoodconsulting.com</p>
    <p style="color:rgba(255,255,255,0.3);font-size:10px;
    margin:12px 0 0">Hai ricevuto questa email perch&eacute;
    hai completato la checklist sul nostro sito.</p>
</td></tr>

</table>
</td></tr></table>
</body>
</html>"""


# ---------- CRITICO (0-8) → Academy ----------

def email_checklist_critico(nome, punteggio, data):
    area_nome, area_val = _area_peggiore(data)

    return (
        _header(f"""{nome}, il tuo locale<br>
        ha bisogno di un intervento.""")
        + _punteggio_badge(punteggio)
        + f"""
<!-- BODY -->
<tr><td style="background:#fff;padding:40px">
    <p style="color:#5a5a5a;font-size:15px;
    line-height:1.9;margin:0 0 24px">
    Ciao {nome},<br><br>
    hai appena completato la checklist operativa
    di SB Food Consulting. Il tuo punteggio
    di <strong>{punteggio}/15</strong> indica
    che ci sono aree critiche che stanno
    costando soldi al tuo locale ogni giorno.</p>

    <!-- AREA PEGGIORE -->
    <div style="background:#f5f2ee;
    border-left:4px solid #c4622d;
    padding:16px 20px;margin:0 0 24px;
    border-radius:0 4px 4px 0">
        <p style="color:#c4622d;font-size:11px;
        font-weight:bold;text-transform:uppercase;
        letter-spacing:1px;margin:0 0 6px">
        Area pi&ugrave; critica</p>
        <p style="color:#1a1a1a;font-size:15px;
        font-weight:bold;margin:0">
        {area_nome}: {area_val}/3</p>
    </div>

    <!-- DETTAGLIO PUNTEGGI -->
    <table width="100%" cellpadding="0"
    cellspacing="0" style="margin:0 0 32px">
    {_punteggi_html(data)}
    </table>

    <p style="color:#5a5a5a;font-size:15px;
    line-height:1.9;margin:0 0 32px">
    <strong>SB Food Academy</strong> &egrave; il percorso
    formativo in 5 moduli costruito esattamente per
    questa situazione. Ogni modulo affronta
    una delle aree della checklist &mdash;
    con metodo operativo applicabile
    da subito nel tuo locale.</p>

    <!-- CTA ACADEMY -->
    <table cellpadding="0" cellspacing="0"
    style="margin:0 auto 32px">
    <tr><td style="background:#c4622d;border-radius:4px">
        <a href="https://www.sbfoodconsulting.com/academy.html"
        style="display:block;padding:16px 32px;color:#ffffff;
        text-decoration:none;font-size:15px;font-weight:bold">
        Scopri SB Food Academy &rarr;</a>
    </td></tr></table>

    <hr style="border:none;border-top:1px solid #edeae5;
    margin:0 0 24px">

    <p style="color:#5a5a5a;font-size:13px;
    line-height:1.8;margin:0">
    Se preferisci parlarne direttamente con Simone
    Braghetta, puoi prenotare una
    <a href="https://calendly.com/sbfoodconsulting-info/30min"
    style="color:#c4622d;text-decoration:none;
    font-weight:bold">chiamata gratuita di 30 minuti</a>.</p>
</td></tr>"""
        + _footer()
    )


# ---------- MEDIO (9-14) → Academy + Call ----------

def email_checklist_medio(nome, punteggio, data):
    area_nome, area_val = _area_peggiore(data)

    return (
        _header(f"""{nome}, abbiamo trovato<br>
        le aree critiche del tuo locale.""")
        + _punteggio_badge(punteggio)
        + f"""
<!-- BODY -->
<tr><td style="background:#fff;padding:40px">
    <p style="color:#5a5a5a;font-size:15px;
    line-height:1.9;margin:0 0 24px">
    Ciao {nome},<br><br>
    hai completato la checklist operativa
    di SB Food Consulting. Con un punteggio
    di <strong>{punteggio}/15</strong>, il tuo locale
    ha delle basi ma ci sono aree specifiche
    che, se migliorate, possono fare
    una differenza concreta sui tuoi numeri.</p>

    <!-- AREA PEGGIORE -->
    <div style="background:#f5f2ee;
    border-left:4px solid #e8a838;
    padding:16px 20px;margin:0 0 24px;
    border-radius:0 4px 4px 0">
        <p style="color:#e8a838;font-size:11px;
        font-weight:bold;text-transform:uppercase;
        letter-spacing:1px;margin:0 0 6px">
        Area da migliorare</p>
        <p style="color:#1a1a1a;font-size:15px;
        font-weight:bold;margin:0">
        {area_nome}: {area_val}/3</p>
    </div>

    <!-- DETTAGLIO PUNTEGGI -->
    <table width="100%" cellpadding="0"
    cellspacing="0" style="margin:0 0 32px">
    {_punteggi_html(data)}
    </table>

    <p style="color:#5a5a5a;font-size:15px;
    line-height:1.9;margin:0 0 16px">
    Ti consigliamo due cose:</p>

    <p style="color:#5a5a5a;font-size:15px;
    line-height:1.9;margin:0 0 8px">
    <strong>1.</strong> <strong>SB Food Academy</strong>
    &mdash; il percorso formativo in 5 moduli
    che copre ogni area della checklist,
    con strumenti operativi pronti all'uso.</p>

    <p style="color:#5a5a5a;font-size:15px;
    line-height:1.9;margin:0 0 32px">
    <strong>2.</strong> <strong>Una chiamata con Simone
    Braghetta</strong> &mdash; 30 minuti gratuiti
    per capire insieme da dove partire.</p>

    <!-- CTA ACADEMY -->
    <table cellpadding="0" cellspacing="0"
    style="margin:0 auto 16px">
    <tr><td style="background:#c4622d;border-radius:4px">
        <a href="https://www.sbfoodconsulting.com/academy.html"
        style="display:block;padding:16px 32px;color:#ffffff;
        text-decoration:none;font-size:15px;font-weight:bold">
        Scopri SB Food Academy &rarr;</a>
    </td></tr></table>

    <!-- CTA CALL -->
    <table cellpadding="0" cellspacing="0"
    style="margin:0 auto 32px">
    <tr><td style="border:2px solid #37393f;border-radius:4px">
        <a href="https://calendly.com/sbfoodconsulting-info/30min"
        style="display:block;padding:14px 28px;color:#37393f;
        text-decoration:none;font-size:14px;font-weight:bold">
        Prenota la chiamata gratuita &rarr;</a>
    </td></tr></table>
</td></tr>"""
        + _footer()
    )


# ---------- BUONO (15-20) → Call consulenza ----------

def email_checklist_buono(nome, punteggio, data):
    return (
        _header(f"""{nome}, il tuo locale<br>
        ha basi solide.""")
        + _punteggio_badge(punteggio)
        + f"""
<!-- BODY -->
<tr><td style="background:#fff;padding:40px">
    <p style="color:#5a5a5a;font-size:15px;
    line-height:1.9;margin:0 0 24px">
    Ciao {nome},<br><br>
    complimenti &mdash; il tuo punteggio
    di <strong>{punteggio}/15</strong> dice che hai
    gi&agrave; una gestione sopra la media.
    Il tuo locale ha fondamenta solide
    su cui costruire.</p>

    <!-- DETTAGLIO PUNTEGGI -->
    <table width="100%" cellpadding="0"
    cellspacing="0" style="margin:0 0 32px">
    {_punteggi_html(data)}
    </table>

    <p style="color:#5a5a5a;font-size:15px;
    line-height:1.9;margin:0 0 32px">
    Il prossimo passo? Una <strong>chiamata
    strategica con Simone Braghetta</strong>
    &mdash; 30 minuti gratuiti per capire
    come portare il tuo locale al livello
    successivo, lavorando sulle aree
    dove c'&egrave; ancora margine.</p>

    <!-- CTA CALL -->
    <table cellpadding="0" cellspacing="0"
    style="margin:0 auto 32px">
    <tr><td style="background:#c4622d;border-radius:4px">
        <a href="https://calendly.com/sbfoodconsulting-info/30min"
        style="display:block;padding:16px 32px;color:#ffffff;
        text-decoration:none;font-size:15px;font-weight:bold">
        Prenota la chiamata gratuita &rarr;</a>
    </td></tr></table>

    <hr style="border:none;border-top:1px solid #edeae5;
    margin:0 0 24px">

    <p style="color:#c4622d;font-size:11px;font-weight:bold;
    letter-spacing:2px;text-transform:uppercase;
    margin:0 0 12px">Vuoi approfondire?</p>

    <p style="color:#5a5a5a;font-size:14px;
    line-height:1.8;margin:0 0 24px">
    SB Food Academy &egrave; il nostro percorso
    formativo in 5 moduli &mdash; anche chi parte
    da un buon punteggio trova strumenti concreti
    per ottimizzare food cost, menu engineering
    e gestione del personale.</p>

    <table cellpadding="0" cellspacing="0"
    style="margin:0 auto">
    <tr><td style="border:2px solid #37393f;border-radius:4px">
        <a href="https://www.sbfoodconsulting.com/academy.html"
        style="display:block;padding:14px 28px;color:#37393f;
        text-decoration:none;font-size:14px;font-weight:bold">
        Scopri il corso &rarr;</a>
    </td></tr></table>
</td></tr>"""
        + _footer()
    )
