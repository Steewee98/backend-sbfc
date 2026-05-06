def email_benvenuto_contatto(nome):
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width">
    </head>
    <body style="margin:0;padding:0;background:#f5f2ee;
    font-family:Arial,sans-serif">

    <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:40px 20px">
    <table width="600" cellpadding="0" cellspacing="0"
    style="max-width:600px;width:100%">

    <!-- HEADER -->
    <tr><td style="background:#37393f;padding:32px 40px;
    text-align:center">
        <p style="color:#f5f2ee;font-size:11px;
        letter-spacing:3px;margin:0 0 8px;
        text-transform:uppercase">SB Food Consulting</p>
        <p style="color:rgba(255,255,255,0.5);font-size:12px;
        margin:0;font-style:italic">
        Dove la ristorazione diventa strategia</p>
    </td></tr>

    <!-- BODY -->
    <tr><td style="background:#ffffff;padding:48px 40px">
        <h2 style="font-family:Georgia,serif;color:#1a1a1a;
        font-size:24px;margin:0 0 24px">
        Grazie per averci contattato, {nome}.</h2>

        <p style="color:#5a5a5a;font-size:15px;line-height:1.8;
        margin:0 0 24px">
        Abbiamo ricevuto la tua richiesta e ti risponderemo
        personalmente entro 24 ore.</p>

        <p style="color:#5a5a5a;font-size:15px;line-height:1.8;
        margin:0 0 32px">
        Nel frattempo, se vuoi fissare subito una chiamata
        conoscitiva gratuita di 30 minuti con Simone Braghetta,
        puoi prenotare direttamente qui:</p>

        <table cellpadding="0" cellspacing="0"
        style="margin:0 auto 40px">
        <tr><td style="background:#c4622d;border-radius:4px">
            <a href="https://calendly.com/sbfoodconsulting-info/30min"
            style="display:block;padding:16px 32px;color:#ffffff;
            text-decoration:none;font-size:15px;font-weight:bold">
            Prenota la tua chiamata gratuita &rarr;</a>
        </td></tr></table>

        <hr style="border:none;border-top:1px solid #edeae5;
        margin:0 0 32px">

        <p style="color:#c4622d;font-size:11px;font-weight:bold;
        letter-spacing:2px;text-transform:uppercase;margin:0 0 12px">
        Scopri SB Food Academy</p>

        <p style="color:#5a5a5a;font-size:14px;line-height:1.8;
        margin:0 0 24px">
        Mentre aspetti, dai un'occhiata al nostro percorso
        formativo online &mdash; 5 moduli operativi costruiti su
        30 anni di lavoro nei ristoranti italiani.</p>

        <table cellpadding="0" cellspacing="0"
        style="margin:0 auto">
        <tr><td style="border:2px solid #37393f;border-radius:4px">
            <a href="https://www.sbfoodconsulting.com/academy.html"
            style="display:block;padding:14px 28px;color:#37393f;
            text-decoration:none;font-size:14px;font-weight:bold">
            Scopri il corso &rarr;</a>
        </td></tr></table>
    </td></tr>

    <!-- FOOTER -->
    <tr><td style="background:#37393f;padding:24px 40px;
    text-align:center">
        <p style="color:rgba(255,255,255,0.5);font-size:12px;
        margin:0 0 8px">SB Food Consulting &mdash; Roma, Italia</p>
        <p style="color:rgba(255,255,255,0.4);font-size:11px;
        margin:0">info@sbfoodconsulting.com</p>
        <p style="color:rgba(255,255,255,0.3);font-size:10px;
        margin:12px 0 0">Hai ricevuto questa email perch&eacute; hai
        compilato il form sul nostro sito.</p>
    </td></tr>

    </table>
    </td></tr></table>
    </body>
    </html>
    """


def email_benvenuto_academy(nome, email, moduli,
                             password_temp=None,
                             prodotto_nome=None,
                             importo=None,
                             stripe_id=None):

    nomi_moduli = {
        1: 'Modulo 1 — Hai davvero il controllo del tuo ristorante?',
        2: 'Modulo 2 — Stai pagando per i risultati giusti?',
        3: 'Modulo 3 — Cosa ti blocca dal crescere?',
        4: "Modulo 4 — L'Arte di Accogliere nel Food",
        5: 'Modulo 5 — Come prepararsi al lancio del tuo locale'
    }

    moduli_lista = ''.join([
        f"""<tr>
        <td style="padding:10px 0;border-bottom:
        1px solid #edeae5;color:#1a1a1a;font-size:14px">
        ✓ {nomi_moduli.get(m, f'Modulo {m}')}</td>
        </tr>""" for m in moduli
    ])

    credenziali_html = ''
    if password_temp:
        credenziali_html = f"""
        <tr><td style="padding:32px 0 0">
        <div style="background:#f5f2ee;border-radius:6px;
        padding:24px;border-left:4px solid #c4622d">
            <p style="margin:0 0 16px;font-size:13px;
            font-weight:600;color:#37393f;
            text-transform:uppercase;letter-spacing:1px">
            Le tue credenziali di accesso</p>
            <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
                <td style="padding:6px 0;font-size:14px;
                color:#5a5a5a;width:80px">Email</td>
                <td style="padding:6px 0;font-size:14px;
                color:#1a1a1a;font-weight:600">{email}</td>
            </tr>
            <tr>
                <td style="padding:6px 0;font-size:14px;
                color:#5a5a5a">Password</td>
                <td style="padding:6px 0;font-size:14px;
                color:#1a1a1a;font-weight:600;
                font-family:monospace;background:#fff;
                padding:4px 8px;border-radius:4px">
                {password_temp}</td>
            </tr>
            </table>
            <p style="margin:16px 0 0;font-size:12px;
            color:#a0a0a0">Ti consigliamo di cambiare
            la password al primo accesso.</p>
        </div>
        </td></tr>
        """
    else:
        credenziali_html = f"""
        <tr><td style="padding:32px 0 0">
        <div style="background:#f5f2ee;border-radius:6px;
        padding:24px;border-left:4px solid #c4622d">
            <p style="margin:0 0 8px;font-size:13px;
            font-weight:600;color:#37393f;
            text-transform:uppercase;letter-spacing:1px">
            Accedi con le tue credenziali esistenti</p>
            <p style="margin:0;font-size:14px;color:#5a5a5a">
            Email: <strong>{email}</strong></p>
        </div>
        </td></tr>
        """

    ricevuta_html = ''
    if importo and prodotto_nome:
        from datetime import datetime
        data_oggi = datetime.utcnow().strftime('%d/%m/%Y')
        ricevuta_html = f"""
        <tr><td style="padding:32px 0 0">
        <p style="margin:0 0 16px;font-size:13px;
        font-weight:600;color:#37393f;
        text-transform:uppercase;letter-spacing:1px">
        Ricevuta di pagamento</p>
        <table width="100%" cellpadding="0" cellspacing="0"
        style="border:1px solid #edeae5;border-radius:6px;
        overflow:hidden">
            <tr style="background:#f5f2ee">
                <td style="padding:12px 16px;font-size:12px;
                font-weight:600;color:#5a5a5a;
                text-transform:uppercase;letter-spacing:1px">
                Descrizione</td>
                <td style="padding:12px 16px;font-size:12px;
                font-weight:600;color:#5a5a5a;
                text-transform:uppercase;letter-spacing:1px;
                text-align:right">Importo</td>
            </tr>
            <tr>
                <td style="padding:16px;font-size:14px;
                color:#1a1a1a">SB Food Academy<br>
                <span style="color:#5a5a5a;font-size:12px">
                {prodotto_nome}</span></td>
                <td style="padding:16px;font-size:14px;
                color:#1a1a1a;font-weight:600;
                text-align:right">{importo:.2f}€</td>
            </tr>
            <tr style="background:#37393f">
                <td style="padding:12px 16px;font-size:14px;
                font-weight:600;color:#fff">Totale pagato</td>
                <td style="padding:12px 16px;font-size:16px;
                font-weight:700;color:#c4622d;
                text-align:right">{importo:.2f}€</td>
            </tr>
        </table>
        <p style="margin:12px 0 0;font-size:12px;
        color:#a0a0a0">Data: {data_oggi} —
        Pagamento processato tramite Stripe</p>
        </td></tr>
        """

    if importo and prodotto_nome and stripe_id:
        ricevuta_html += f"""
        <tr><td style="padding-top:12px">
        <a href="https://web-production-f3794.up.railway.app/api/ricevuta/{stripe_id}?email={email}"
        style="display:inline-block;background:#f5f2ee;
        border:1px solid #d9d4cc;color:#37393f;
        text-decoration:none;padding:10px 20px;
        border-radius:4px;font-size:13px;font-weight:600">
        ↓ Scarica ricevuta PDF</a>
        </td></tr>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,
    initial-scale=1.0"></head>
    <body style="margin:0;padding:0;background:#f5f2ee;
    font-family:Arial,sans-serif">

    <table width="100%" cellpadding="0" cellspacing="0"
    style="background:#f5f2ee">
    <tr><td align="center" style="padding:40px 20px">
    <table width="600" cellpadding="0" cellspacing="0"
    style="max-width:600px;width:100%">

    <!-- HEADER -->
    <tr><td style="background:#37393f;padding:40px;
    text-align:center;border-radius:6px 6px 0 0">
        <p style="color:#c4622d;font-size:11px;
        letter-spacing:3px;margin:0 0 12px;
        text-transform:uppercase;font-weight:600">
        SB Food Academy</p>
        <h1 style="color:#ffffff;font-family:Georgia,serif;
        font-size:28px;margin:0 0 8px;font-weight:400">
        Benvenuto, {nome}.</h1>
        <p style="color:rgba(255,255,255,0.6);
        font-size:14px;margin:0">
        Il tuo percorso formativo è iniziato.</p>
    </td></tr>

    <!-- BODY -->
    <tr><td style="background:#ffffff;padding:40px;
    border-radius:0 0 6px 6px">
    <table width="100%" cellpadding="0" cellspacing="0">

        <!-- INTRO -->
        <tr><td style="padding-bottom:24px">
        <p style="margin:0;font-size:15px;color:#5a5a5a;
        line-height:1.8">Grazie per aver acquistato
        SB Food Academy. Hai accesso immediato
        ai tuoi contenuti — inizia subito dal link
        qui sotto.</p>
        </td></tr>

        <!-- CTA -->
        <tr><td style="padding-bottom:32px;text-align:center">
        <a href="https://www.sbfoodconsulting.com/academy.html#area-studenti"
        style="display:inline-block;background:#c4622d;
        color:#ffffff;text-decoration:none;
        padding:16px 40px;border-radius:4px;
        font-size:15px;font-weight:600;
        letter-spacing:0.5px">
        Accedi al corso →</a>
        </td></tr>

        <!-- MODULI ACQUISTATI -->
        <tr><td>
        <p style="margin:0 0 16px;font-size:13px;
        font-weight:600;color:#37393f;
        text-transform:uppercase;letter-spacing:1px">
        Contenuti sbloccati</p>
        <table width="100%" cellpadding="0" cellspacing="0">
        {moduli_lista}
        </table>
        </td></tr>

        <!-- CREDENZIALI -->
        {credenziali_html}

        <!-- RICEVUTA -->
        {ricevuta_html}

        <!-- SUPPORTO -->
        <tr><td style="padding-top:32px;
        border-top:1px solid #edeae5;margin-top:32px">
        <p style="margin:0;font-size:13px;color:#5a5a5a;
        line-height:1.8">Hai domande o hai bisogno
        di supporto? Rispondi a questa email o
        scrivici a
        <a href="mailto:info@sbfoodconsulting.com"
        style="color:#c4622d;text-decoration:none">
        info@sbfoodconsulting.com</a></p>
        </td></tr>

    </table>
    </td></tr>

    <!-- FOOTER -->
    <tr><td style="padding:24px;text-align:center">
        <p style="margin:0 0 4px;font-size:12px;
        color:#a0a0a0">SB Food Consulting — Roma, Italia</p>
        <p style="margin:0;font-size:11px;color:#c0bbb5">
        © 2025 SB Food Consulting.
        Tutti i diritti riservati.</p>
    </td></tr>

    </table>
    </td></tr></table>
    </body>
    </html>
    """
